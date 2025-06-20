import os
import sqlite3
from flask import Flask, Blueprint, render_template, request, session, redirect, url_for, jsonify, flash
from flask_login import current_user, login_required, login_user
from werkzeug.utils import secure_filename
from datetime import date, datetime
from .badge import check_contest_winner_badges
from flask_cors import CORS #Allows external website to access API

app = Flask(__name__, static_folder='static')
app.secret_key = 'your_secret_key'
contestmanagement_bp = Blueprint('contestmanagement', __name__, template_folder='templates', static_folder='static')
CORS(app) 

UPLOAD_FOLDER = 'Website/static/contest' #Folder to store uploaded files
ALLOWED_EXTENSIONS = {'png','jpg','jpeg'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def get_db_connection():
    db_path = os.path.join(os.path.dirname(__file__), '..', 'instance', 'datebase.db')
    db_path = os.path.abspath(db_path) 
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def initialize_database():
    with get_db_connection() as conn:
        #Enable Foreign Key Constraints 
        conn.execute("PRAGMA foreign_keys = ON;")  #Stops submissions from referencing non-existent contests

        conn.execute('''
            CREATE TABLE IF NOT EXISTS submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                contest_id INTEGER NOT NULL,
                description TEXT,
                file_path TEXT NOT NULL,
                rules_agree BOOLEAN NOT NULL,
                submission_date DATE DEFAULT DATE('now'),
                FOREIGN KEY (contest_id) REFERENCES contests (id)
            )
        ''')
        conn.commit()

        #Check if admins are already inserted
        existing_admins = conn.execute("SELECT * FROM user WHERE role='admin'").fetchall()

@app.route('/login', methods=['POST', 'GET'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        print(f"DEBUG: login POST hit — email = {email}")

        conn = get_db_connection()
        user = conn.execute('''
            SELECT rowid AS id, email, role
            FROM user
            WHERE email = ?
        ''', (email,)).fetchone()
        conn.close()

        print(f"DEBUG: Raw user query result = {user}") 

        if user:
            user_obj = CustomUser(id=user['id'], email=user['email'], role=user['role'])
            login_user(user_obj)

            print("DEBUG: Logged in user:", user_obj)

            session['role'] = user_obj.role
            session.permanent = True  #Make the session permanent
            session.modified = True  #Mark session as modified to ensure it is saved
            print(f"DEBUG: session role set to {session['role']}")

            return redirect(url_for('contestmanagement.contest_page'))
        else:
            flash("Invalid credentials!", "error")
            return render_template('login.html')

    return render_template('login.html')

@contestmanagement_bp.route("/contest_page")
def contest_page():
    print(f"DEBUG: current_user = {current_user}")  # Debugging current_user 

    user_role = getattr(current_user, 'role', 'user')
    print(f"DEBUG: user_role = {user_role}")

    conn = get_db_connection()
    contests = conn.execute("SELECT * FROM contests").fetchall()  # Get all contests
    conn.close()
    
    today = date.today()

    contests = [dict(c) for c in contests]

    for c in contests:
        c["start_date"] = datetime.strptime(c["start_date"], "%Y-%m-%d").date()  #Convert string to date
        c["end_date"] = datetime.strptime(c["end_date"], "%Y-%m-%d").date()  #Convert string to date
        c["voting_end"] = datetime.strptime(c["voting_end"], "%Y-%m-%d").date()

    #Categorize contests based on proper date comparisons
    ongoing_contests = sorted(
        [c for c in contests if c["start_date"] <= today and c["voting_end"] >= today], key=lambda x: x["voting_end"]
    )  #Sort ongoing contests so those ending soonest are first

    upcoming_contests = sorted(
        [c for c in contests if c["start_date"] > today], key=lambda x: x["start_date"]
    )  #Sort upcoming contests by start date

    completed_contests = sorted(
        [c for c in contests if c["voting_end"] < today], key=lambda x: x["voting_end"], reverse=True 
    )  #Sort completed contests with the latest ended at the top

    PER_PAGE = 3

    page_ongoing = request.args.get('page_ongoing', 1, type=int)
    page_upcoming = request.args.get('page_upcoming', 1, type=int)
    page_completed = request.args.get('page_completed', 1, type=int)

    section = request.args.get('section', 'ongoing')

    def paginate(items, page):
        start = (page - 1) * PER_PAGE
        end = start + PER_PAGE
        total_pages = (len(items) + PER_PAGE - 1) // PER_PAGE
        return items[start:end], total_pages
    
    ongoing_page_items, ongoing_total_pages = paginate(ongoing_contests, page_ongoing)
    upcoming_page_items, upcoming_total_pages = paginate(upcoming_contests, page_upcoming)
    completed_page_items, completed_total_pages = paginate(completed_contests, page_completed)
    
    return render_template("contest.html", contests=contests, user=current_user, user_role=user_role, user_has_submitted=user_has_submitted, 
                           ongoing_contests=ongoing_page_items, upcoming_contests=upcoming_page_items, completed_contests=completed_page_items, 
                           ongoing_page=page_ongoing, ongoing_total_pages=ongoing_total_pages, upcoming_page=page_upcoming, upcoming_total_pages=upcoming_total_pages, completed_page=page_completed, completed_total_pages=completed_total_pages, section=section)

@contestmanagement_bp.route('/create_contest', methods=['GET', 'POST'])
@login_required 
def create_contest():
    if hasattr(current_user, 'role') and current_user.role == 'admin':
        if request.method == 'POST':
            contest_name = request.form['contest_name']
            start_date = request.form['start_date']
            end_date = request.form['end_date']
            voting_start = request.form['voting_start']
            voting_end = request.form['voting_end']
            result_announcement = request.form['result_announcement']
            purpose = request.form['purpose']
            rules = request.form['rules']
            prizes = request.form['prizes']
            file = request.files['contest_banner']
        
            if not file or file.filename == '':
                flash("Banner is required to create a contest!", "error")
                return redirect(url_for('contestmanagement.create_contest'))

            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)  #Ensure folder exists
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file_path = file_path.replace("\\", "/")  #Convert backslashes to forward slashes
                file.save(file_path)  # Save the actual file
                banner_url = f"contest/{filename}"

            with get_db_connection() as conn:
                conn.execute('''
                    INSERT INTO contests (name, start_date, end_date, voting_start, voting_end, result_announcement, purpose, rules, prizes, banner_url) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (contest_name, start_date, end_date, voting_start, voting_end, result_announcement, purpose, rules, prizes, banner_url))
                conn.commit()  #Save changes

            return redirect(url_for('contestmanagement.contest_page'))  #Send admins back to the contest page after creating a contest

        return render_template('create_contest.html', user=current_user) 
    else:
        flash("Access Denied. Admins Only!", "error")
        return redirect(url_for('contestmanagement.contest_page')) #Send non-admins back to the contest page
        
@contestmanagement_bp.route('/contest_submission/<int:contest_id>', methods=['GET', 'POST'])
def submit_contest(contest_id):
    conn = get_db_connection()
    contest = conn.execute("SELECT id, name FROM contests WHERE id = ?", (contest_id,)).fetchone()

    if not current_user.is_authenticated:
        flash("You must be logged in to join!", category="error")
        return redirect(url_for('auth.login'))
    
    if contest is None:
        flash("Invalid contest. You cannot submit an entry.", "error")
        return redirect(url_for('contestmanagement.contest_page'))
    
    if user_has_submitted(current_user.Name, contest_id):
        flash("You have already submitted an entry for this contest.", "error")
        return redirect(url_for('contestmanagement.contest_page'))

    if request.method == 'POST':
        print("Received Form Data:", request.form)  #Debugging 
        description = request.form['description']
        file = request.files['file']
        rules_agree = bool(request.form.get('rulesAgree')) #Convert to boolean

       #Validate the file type
        if file and allowed_file(file.filename):
            try:
                filename = secure_filename(file.filename)
                os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file_path = file_path.replace("\\", "/")  #Convert backslashes to forward slashes
                file.save(file_path)  #Save the file inside the contest folder
            except Exception as e:
                flash(f"Error saving file: {e}", "error")
                return redirect(url_for('contestmanagement.submit_contest', contest_id=contest_id))
        else:
            flash("Invalid file format! Only JPG, JPEG and PNG are allowed.", "error")
            return redirect(url_for('contestmanagement.submit_contest', contest_id=contest_id))

        #Save the submission to the database
        with get_db_connection() as conn:
                conn.execute('''
                    INSERT INTO submissions (name, contest_id, description, file_path, rules_agree) 
                    VALUES (?, ?, ?, ?, ?)
                ''', (current_user.Name, contest_id, description, file_path, rules_agree))
                conn.commit() #Save changes

        return redirect(url_for('contestmanagement.contest_page'))  #Sends user back to the contest page after submission

    return render_template("contest_submission.html", contest_id=contest_id, user=current_user, contest=contest)

def user_has_submitted(name, contest_id):
    if not name or not contest_id:
        return False

    conn = get_db_connection()
    existing_entry = conn.execute(
        "SELECT * FROM submissions WHERE name = ? AND contest_id = ?",
        (name, contest_id)
    ).fetchone()
    conn.close()

    return existing_entry is not None

#voting system
@contestmanagement_bp.route('/voting/<int:contest_id>', methods=['GET', 'POST'])
def voting(contest_id):
    conn = get_db_connection()

    #ensure the user is logged in before voting
    if not current_user.is_authenticated:
        flash("You must be logged in to vote!", category="error")
        return redirect(url_for('auth.login'))

    contest = conn.execute("SELECT name, voting_start, voting_end FROM contests WHERE id = ?", (contest_id,)).fetchone()
    if not contest:
        flash("Contest not found!", category="error")
        return redirect(url_for('contestmanagement.contest_page'))

    contest_name = contest["name"]

    #ensure voting times have full date-time format
    voting_start_str = contest["voting_start"]
    voting_end_str = contest["voting_end"]

    if len(voting_start_str) == 10:  #if stored as "YYYY-MM-DD"
        voting_start_str += " 00:00:00"  #add default time
    if len(voting_end_str) == 10:  #if stored as "YYYY-MM-DD"
        voting_end_str += " 23:59:59"  #add end-of-day time

    #convert to datetime format
    voting_start = datetime.strptime(voting_start_str, "%Y-%m-%d %H:%M:%S")
    voting_end = datetime.strptime(voting_end_str, "%Y-%m-%d %H:%M:%S")

    current_time = datetime.now()

    #redirect to countdown page if voting hasn't started yet
    if current_time < voting_start:
        time_left = voting_start - current_time
        days_left = time_left.days
        hours_left = time_left.seconds // 3600
        minutes_left = (time_left.seconds % 3600) // 60

        return render_template("voting_countdown.html", contest_name=contest_name, days_left=days_left, hours_left=hours_left,minutes_left=minutes_left, user=current_user)

    #redirect to contest page if voting has ended
    if current_time > voting_end:
        flash("Voting has ended!", category="error")
        return redirect(url_for('contestmanagement.contest_page'))

    participants = conn.execute("SELECT id, name, file_path, votes, description FROM submissions WHERE contest_id = ?", (contest_id,)).fetchall()
    conn.close()

    return render_template("voting.html", contest_name=contest_name, contest_id=contest_id, participants=participants, user=current_user)

@contestmanagement_bp.route('/submit_vote/<int:contest_id>', methods=['POST'])
def submit_vote(contest_id):
    selected_participant_id = request.form.get("vote")

    if not selected_participant_id:
        flash("Please select a participant to vote!", category="error")
        return redirect(url_for('contestmanagement.voting', contest_id=contest_id))

    conn = get_db_connection()

    #ensure valid participant
    participant = conn.execute("SELECT id FROM submissions WHERE id = ? AND contest_id = ?", (selected_participant_id, contest_id)).fetchone()
    if not participant:
        flash("Invalid participant!", category="error")
        return redirect(url_for('contestmanagement.voting', contest_id=contest_id))

    #check if user has already voted
    user_id = current_user.id 
    has_voted = conn.execute("SELECT id FROM votes WHERE user_id = ? AND contest_id = ?", (user_id, contest_id)).fetchone()

    if has_voted:
        flash("You have already voted in this contest!", category="error")
        return redirect(url_for('contestmanagement.voting', contest_id=contest_id))

    #add vote to db
    conn.execute("INSERT INTO votes (user_id, contest_id, participant_id) VALUES (?, ?, ?)", (user_id, contest_id, selected_participant_id))

    #update votes count
    conn.execute("UPDATE submissions SET votes = COALESCE(votes, 0) + 1 WHERE id = ?", (selected_participant_id,))
    conn.commit()
    conn.close()

    flash("Your vote has been recorded!", category="success")
    return redirect(url_for('contestmanagement.voting', contest_id=contest_id))

@contestmanagement_bp.route('/view_result/<int:contest_id>')
def view_result(contest_id):
    conn = get_db_connection()

    if not current_user.is_authenticated:
        flash("You must be logged in to view result!", category="error")
        return redirect(url_for('auth.login'))
    
    #fetch contest details, including result announcement date
    contest = conn.execute("SELECT name, result_announcement FROM contests WHERE id = ?", (contest_id,)).fetchone()
    if not contest:
        flash("Contest not found!", category="error")
        return redirect(url_for('contestmanagement.contest_page'))

    #convert stored announcement date to datetime format
    announcement_date_str = contest["result_announcement"]
    
    if len(announcement_date_str) == 10:  #if format is 'YYYY-MM-DD'
        announcement_date_str += " 00:00:00"  #append default time

    announcement_date = datetime.strptime(announcement_date_str, "%Y-%m-%d %H:%M:%S")
    current_time = datetime.now()

    if current_time < announcement_date:
        time_left = announcement_date - current_time
        days_left = time_left.days
        hours_left = (time_left.seconds // 3600)
        minutes_left = (time_left.seconds % 3600) // 60

        return render_template("result_countdown.html", contest_name=contest["name"], 
                               days_left=days_left, hours_left=hours_left, minutes_left=minutes_left, user=current_user)

    participants = conn.execute("""
        SELECT name, description, file_path, votes 
        FROM submissions 
        WHERE contest_id = ?
        ORDER BY votes DESC
    """, (contest_id,)).fetchall()
    conn.close()

    if not participants:
        flash("No submissions found for this contest.", category="error")
        return redirect(url_for('contestmanagement.contest_page'))

    #determine winners
    top_vote = participants[0]['votes']
    winners = [p for p in participants if p['votes'] == top_vote]

    winner_names = [w['name'] for w in winners]
    show_claim_button = getattr(current_user, 'Name', None) in winner_names

    # Get the contest winner badge id
    with get_db_connection() as conn:
        badge = conn.execute("SELECT id FROM badge WHERE criteria = ?", ('contest_winner',)).fetchone()
        badge_id = badge['id'] if badge else None

    return render_template("view_result.html", contest_name=contest["name"], participants=participants, winners=winners, 
                           show_claim_button=show_claim_button, contest_id=contest_id, user=current_user, badge_id=badge_id)

def get_winners(contest_id):
    conn = get_db_connection()
    participants = conn.execute("""
        SELECT name, votes FROM submissions
        WHERE contest_id = ?
        ORDER BY votes DESC
    """, (contest_id,)).fetchall()
    conn.close()

    if not participants:
        return []

    top_vote = participants[0]['votes']
    winners = [p for p in participants if p['votes'] == top_vote]
    return winners

#Calendar in homepage
@contestmanagement_bp.route('/api/contests')
def get_contests():
    conn = get_db_connection()
    contests = conn.execute(
        'SELECT name, start_date FROM contests WHERE start_date >= CURRENT_DATE ORDER BY start_date ASC'
    ).fetchall()
    conn.close()

    contest_events = [{"title": contest["name"], "start": contest["start_date"]} for contest in contests]
    return jsonify(contest_events)

@contestmanagement_bp.route('/get_upcoming_contest')
def get_upcoming_contest():
    conn = get_db_connection()
    contests = conn.execute(
        'SELECT name, start_date FROM contests WHERE start_date >= CURRENT_DATE ORDER BY start_date ASC'
    ).fetchall()
    conn.close()

    if contests:  # Check if there are any upcoming contests
        next_contest = contests[0]  # Get the first upcoming contest
        return jsonify({'start_date': next_contest['start_date']})
    else:
        return jsonify({'start_date': None})

if __name__ == '__main__':
    #Ensure the upload folder exists
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])

    initialize_database() 

    #Creates database table if it doesn't exist
    with get_db_connection() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS contests ( 
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                voting_start TEXT NOT NULL,
                voting_end TEXT NOT NULL,
                result_announcement TEXT NOT NULL,
                purpose TEXT NOT NULL,
                rules TEXT NOT NULL,
                prizes TEXT NOT NULL,
                banner_url TEXT NOT NULL
            )
        ''')
        #Create the table if it doesn't exists
        #Name of the table is contests
        #id INTEGER PRIMARY KEY AUTOINCREMENT Adds an id to the table
        #TEXT NOT NULL Adds a column for the banner, name, start_date, end_date, voting_start, voting_end, result_announcement, purpose, rules and prizes which are a must to fill in

        conn.commit()

    app.run(debug=True)