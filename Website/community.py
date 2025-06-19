import os
import sqlite3
from datetime import datetime
from flask import Blueprint, request,flash, redirect, render_template, url_for
from flask_login import current_user
from werkzeug.utils import secure_filename

community_bp = Blueprint('community', __name__, template_folder='templates')

POSTS_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'posts')
COMMENTS_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'comments')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'mov', 'avi'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_db_connection():
    db_path = os.path.join(os.path.dirname(__file__), '..', 'instance', 'datebase.db')
    db_path = os.path.abspath(db_path) 
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def get_cat_names():
    conn = get_db_connection()
    if conn is None:
        return []
    cursor = conn.cursor()
    cursor.execute('SELECT name FROM profiles')
    cat_names = [row['name'] for row in cursor.fetchall()]

    conn.close()
    return cat_names

# All Posts
@community_bp.route('/community_feature')
def community_feature(): 
    user_id = current_user.id if current_user.is_authenticated else -1
    sort = request.args.get('sort', 'date_desc') 
   
    if sort == 'date_asc': 
        order_by = 'post.created_at ASC'
    elif sort == 'date_desc':
        order_by = 'post.created_at DESC'
    elif sort == 'likes_desc':
        order_by = 'like_count DESC'
    
    else:
        order_by = 'post.user_id'
    
    conn = get_db_connection()

    query = f'''
        SELECT post.*, user.name, user.profile_picture,
            (SELECT COUNT(*) FROM likes WHERE likes.post_id = post.post_id) AS like_count,
            (SELECT COUNT(*) FROM comment WHERE comment.post_id = post.post_id) AS comment_count,
            CASE 
                WHEN EXISTS (
                    SELECT 1 FROM likes 
                    WHERE likes.post_id = post.post_id AND likes.user_id = ?
                ) THEN 1
                ELSE 0
            END AS liked_by_current_user
        FROM post 
        JOIN user ON post.user_id = user.id 
        GROUP BY post.post_id
        ORDER BY {order_by}
    '''
    posts = conn.execute(query, (user_id,)).fetchall()
    conn.close()

    return render_template("community_index.html", user=current_user, posts=posts, sort=sort, cat_names=get_cat_names())


# Post Detail
@community_bp.route('/post/<int:post_id>')
def post_detail(post_id):
    conn = get_db_connection()
    
    post = conn.execute('''
        SELECT 
            post.*, 
            user.name,
            user.profile_picture,
                (SELECT COUNT(*) FROM likes WHERE likes.post_id = post.post_id) AS like_count,
                (SELECT COUNT(*) FROM comment WHERE comment.post_id = post.post_id) AS comment_count,
            CASE 
                WHEN EXISTS (
                    SELECT 1 FROM likes 
                    WHERE likes.post_id = post.post_id AND likes.user_id = ?
                ) THEN 1
                ELSE 0
            END AS liked_by_current_user
        FROM post 
        JOIN user ON post.user_id = user.id
        WHERE post.post_id = ?
    ''', (
        current_user.id if current_user.is_authenticated else -1,
        post_id
    )).fetchone()

    if post is None:
        conn.close()
        flash("The post does not exist or has been deleted.", category="error")
        return redirect(url_for('community.community_feature'))

    comments = conn.execute('''
        SELECT 
            comment.*,
            user.name AS name, 
            user.profile_picture AS profile_picture,
            (SELECT COUNT(*) FROM comment_like WHERE comment_like.comment_id = comment.id) AS like_count,
            CASE 
                WHEN EXISTS (
                    SELECT 1 FROM comment_like 
                    WHERE comment_like.comment_id = comment.id AND comment_like.user_id = ?
                ) THEN 1
                ELSE 0
            END AS liked_by_current_user
        FROM comment
        JOIN user ON comment.user_id = user.id
        WHERE comment.post_id = ?
        ORDER BY comment.created_at DESC
    ''', (current_user.id if current_user.is_authenticated else -1, post_id)).fetchall()

    grouped_comments = {}
    for comment in comments:
        parent_id = comment['parent_id']
        if parent_id not in grouped_comments:
            grouped_comments[parent_id] = []
        grouped_comments[parent_id].append(comment)
    conn.close()

    return render_template("community_detail.html", post=post, comments=comments, grouped_comments=grouped_comments, user=current_user)

# Create Post
@community_bp.route('/post/create', methods=['POST'])
def create_post():
    if not current_user.is_authenticated:
        flash("You must be logged in to create post!", category="error")
        return redirect(url_for('auth.login'))
    
    content = request.form['content']
    cat_hashtag = request.form.get('cat_hashtag')
    user_id = current_user.id
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    media_files = request.files.getlist('media')
    media_url = None

    if len(content.split()) > 100:
        flash("Post content must be 100 words or less!", category="error")
        return redirect(url_for('community.community_feature'))

    media_urls = []

    for media in media_files:
        if media and allowed_file(media.filename):
            os.makedirs(POSTS_FOLDER, exist_ok=True)
            filename = secure_filename(media.filename)
            media.save(os.path.join(POSTS_FOLDER, filename))
            media_urls.append(f"posts/{filename}") 

    media_url = ';'.join(media_urls) if media_urls else None        

    conn = get_db_connection()
    conn.execute(
        '''
        INSERT INTO post (user_id, content, media_url, created_at, cat_hashtag)
        VALUES (?, ?, ?, ?, ?)
        ''',
        (user_id, content, media_url, created_at, cat_hashtag)
    )
    conn.commit()
    conn.close()

    return redirect(url_for('community.community_feature'))


# Hashtag Posts
@community_bp.route('/hashtag/<string:hashtag>')
def hashtag_posts(hashtag):
    sort = request.args.get('sort', 'date_desc')

    conn = get_db_connection()

    if sort == 'date_asc':
        order_by = 'post.created_at ASC'
    elif sort == 'date_desc':
        order_by = 'post.created_at DESC'
    elif sort == 'likes_desc':
        order_by = 'like_count DESC'
    else:
        order_by = 'post.created_at DESC'

    posts = conn.execute(
        f'''
        SELECT post.*, user.name, user.profile_picture,
            (SELECT COUNT(*) FROM likes WHERE likes.post_id = post.post_id) AS like_count,
            (SELECT COUNT(*) FROM comment WHERE comment.post_id = post.post_id) AS comment_count,
            CASE 
                WHEN EXISTS (
                    SELECT 1 FROM likes 
                    WHERE likes.post_id = post.post_id AND likes.user_id = ?
                ) THEN 1
                ELSE 0
            END AS liked_by_current_user
        FROM post
        JOIN user ON post.user_id = user.id
        WHERE post.cat_hashtag = ?
        GROUP BY post.post_id
        ORDER BY {order_by}
        ''',
        (current_user.id if current_user.is_authenticated else -1, hashtag)
    ).fetchall()

    conn.close()

    return render_template('community_index.html',user=current_user, posts=posts, sort=sort, cat_names=get_cat_names())

#My Post
@community_bp.route('/my-posts')
def my_posts():
    if not current_user.is_authenticated:
        flash("You must be logged in to view your posts!", category="error")
        return redirect(url_for('auth.login'))
    
    conn = get_db_connection()
    posts = conn.execute('''
        SELECT 
            post.*, 
            user.name, 
            user.profile_picture,
            (SELECT COUNT(*) FROM likes WHERE likes.post_id = post.post_id) AS like_count,
            (SELECT COUNT(*) FROM comment WHERE comment.post_id = post.post_id) AS comment_count
        FROM post
        JOIN user ON post.user_id = user.id
        WHERE post.user_id = ?
        ORDER BY post.created_at DESC
    ''', (current_user.id,)).fetchall()
    conn.close()
    return render_template("my_posts.html", user=current_user, posts=posts, cat_names=get_cat_names())


# Edit and Delete Post
@community_bp.route('/post/edit/<int:post_id>', methods=['POST'])
def edit_post(post_id):
    content = request.form['content']
    cat_hashtag = request.form.get('cat_hashtag')
    conn = get_db_connection()
    post = conn.execute('SELECT * FROM post WHERE post_id = ?', (post_id,)).fetchone()

    if len(content.split()) > 100:
        flash("Post content must be 100 words or less!", category="error")
        return redirect(url_for('community.my_posts'))
    
    if post and post['user_id'] == current_user.id:
        conn.execute(
            'UPDATE post SET content = ?, cat_hashtag = ? WHERE post_id = ?',
            (content, cat_hashtag, post_id)
        )
        conn.commit()
        
    conn.close()
    return redirect(url_for('community.my_posts'))

@community_bp.route('/post/delete/<int:post_id>', methods=['POST'])  # Route to delete a post, accepts only POST requests
def delete_post(post_id):
    conn = get_db_connection()

    # Retrieve the post data from the database
    post = conn.execute('SELECT * FROM post WHERE post_id = ?', (post_id,)).fetchone()

    # Check if the post exists and belongs to the current user
    if post and post['user_id'] == current_user.id:

        # Delete all likes associated with the post
        conn.execute('DELETE FROM likes WHERE post_id = ?', (post_id,))

        # Delete all comments associated with the post
        conn.execute('DELETE FROM comment WHERE post_id = ?', (post_id,))

        # Delete all comment's like associated with the post
        conn.execute('DELETE FROM comment_like WHERE post_id = ?', (post_id,))        

        # Delete the post from the database
        conn.execute('DELETE FROM post WHERE post_id = ?', (post_id,))
        conn.commit()

        # Delete all media files associated with the post
        media_files = post['media_url']
        if media_files:
            files = media_files.split(';')
            for file_path in files:
                filename = os.path.basename(file_path)
                filepath = os.path.join(POSTS_FOLDER, filename)
                if os.path.exists(filepath):
                    os.remove(filepath)                    

    conn.close()
    # Redirect back to the community feature page after deletion
    return redirect(url_for('community.my_posts'))


# Like and Unlike Post
@community_bp.route('/post/like/<int:post_id>', methods=['POST'])
def like_post(post_id):
    if not current_user.is_authenticated:
        flash("You must be logged in to like post!", category="error")
        return redirect(url_for('auth.login')) 
    
    user_id = current_user.id
    sort = request.form.get('sort', 'date_desc')
    conn = get_db_connection()
    # Check if the post has already been liked to avoid duplicate likes
    existing_like = conn.execute(
        'SELECT 1 FROM likes WHERE user_id = ? AND post_id = ?',
        (user_id, post_id)
    ).fetchone()

    if not existing_like:
        conn.execute(
            'INSERT INTO likes (user_id, post_id) VALUES (?, ?)',
            (user_id, post_id)
        )
        conn.commit()

    conn.close()
    referer = request.referrer

    if 'community_feature' in referer or '/community_feature' in referer:
        return redirect(url_for('community.community_feature', sort=sort))
    
    return redirect(url_for('community.post_detail', post_id=post_id))

@community_bp.route('/post/unlike/<int:post_id>', methods=['POST'])
def unlike_post(post_id):
    user_id = current_user.id
    sort = request.form.get('sort', 'date_desc')

    conn = get_db_connection()
    conn.execute(
        'DELETE FROM likes WHERE user_id = ? AND post_id = ?',
        (user_id, post_id)
    )
    conn.commit()
    conn.close()

    referer = request.referrer

    if 'community_feature' in referer or '/community_feature' in referer:
        return redirect(url_for('community.community_feature', sort=sort))

    return redirect(url_for('community.post_detail', post_id=post_id))

# comment
@community_bp.route('/post/<int:post_id>/comment', methods=['POST'])
def add_comment(post_id):
    if not current_user.is_authenticated:
        flash("You must be logged in to comment!", category="error")
        return redirect(url_for('auth.login')) 
    
    content = request.form.get('content', '').strip() 
    media = request.files.get('media')
    media_url = None
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user_id = current_user.id
    parent_id = request.form.get('parent_id')

    if not parent_id:
        parent_id = None    

    if not content and not media:
        flash("You must provide either text or media for your comment!", category="error")
        return redirect(f'/post/{post_id}#comments')

    if media and allowed_file(media.filename):
        os.makedirs(COMMENTS_FOLDER, exist_ok=True)
        filename = secure_filename(media.filename)
        media.save(os.path.join(COMMENTS_FOLDER, filename))
        media_url = f"comments/{filename}"
    
    conn = get_db_connection()

    result = conn.execute(
        'SELECT MAX(floor) FROM comment WHERE post_id = ?', (post_id,)
    ).fetchone()
    max_floor = result[0] if result[0] is not None else 0
    new_floor = max_floor + 1

    conn.execute(
        '''INSERT INTO comment (content, media_url, created_at, post_id, user_id,parent_id, floor) 
           VALUES (?, ?, ?, ?, ?, ?, ?)''', 
        (content, media_url, created_at, post_id, user_id, parent_id, new_floor) 
    )
    conn.commit()
    conn.close()

    return redirect(f'/post/{post_id}#comments')

@community_bp.route('/comment/like/<int:comment_id>', methods=['POST'])
def like_comment(comment_id):
    if not current_user.is_authenticated:
        flash("You must be logged in to like a comment!", category="error")
        return redirect(url_for('auth.login')) 
    
    user_id = current_user.id
    conn = get_db_connection()

    result = conn.execute(
        'SELECT post_id FROM comment WHERE id = ?',
        (comment_id,)
    ).fetchone()
    post_id = result['post_id']

    existing_like = conn.execute(
        'SELECT 1 FROM comment_like WHERE user_id = ? AND comment_id = ?',
        (user_id, comment_id)
    ).fetchone()

    if not existing_like:
        conn.execute(
            'INSERT INTO comment_like (user_id, comment_id, post_id) VALUES (?, ?, ?)',
            (user_id, comment_id, post_id)
        )
        conn.commit()

    conn.close()
    return redirect(request.referrer)

@community_bp.route('/comment/unlike/<int:comment_id>', methods=['POST'])
def unlike_comment(comment_id):
    user_id = current_user.id
    conn = get_db_connection()

    conn.execute(
        'DELETE FROM comment_like WHERE user_id = ? AND comment_id = ?',
        (user_id, comment_id)
    )
    conn.commit()
    conn.close()

    return redirect(request.referrer)

@community_bp.route('/comment/delete/<int:comment_id>', methods=['POST'])
def delete_comment(comment_id):
    conn = get_db_connection()

    def delete_with_replies(comment_id):
        comment = conn.execute('SELECT media_url FROM comment WHERE id = ?', (comment_id,)).fetchone()

        child_comments = conn.execute('SELECT id FROM comment WHERE parent_id = ?', (comment_id,)).fetchall()
        for child in child_comments:
            delete_with_replies(child['id'])

        if comment and comment['media_url']:
            filename = os.path.basename(comment['media_url'])
            filepath = os.path.join(COMMENTS_FOLDER, filename)
            if os.path.exists(filepath):
                os.remove(filepath)

        conn.execute('DELETE FROM comment_like WHERE comment_id = ?', (comment_id,))            
        conn.execute('DELETE FROM comment WHERE id = ?', (comment_id,)) 
    
    delete_with_replies(comment_id)

    conn.commit()
    conn.close()

    flash("Comment deleted successfully!", category="success")
    return redirect(request.referrer)