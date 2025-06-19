import os
import sqlite3
import random
import re
from flask import flash, Blueprint, render_template, request, redirect, url_for, current_app
from flask_login import current_user
from graphviz import Digraph

relationship_bp = Blueprint('relationship', __name__, template_folder='templates')

def get_db_connection():
    # Compute the path for the database file
    db_path = os.path.join(os.path.dirname(__file__), '..', 'instance', 'datebase.db')
    db_path = os.path.abspath(db_path) 
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def get_cat_photos(all_cats):
    cat_photos = {}
    for cat in all_cats:
        if cat['photo'] and os.path.exists(os.path.join(current_app.static_folder, 'uploads', cat['photo'])):
            cat_photos[cat['name']] = os.path.join(current_app.static_folder, 'uploads', cat['photo'])
        else:
            cat_photos[cat['name']] = os.path.join(current_app.static_folder, 'uploads', 'default.png')
    return cat_photos

#generate the relationship graph
def generate_graph(relations, cat_photos, filename='cat_relationship_tree'):
    if not relations:
        return None

    dot = Digraph(comment='Cat Relationship Tree', format='svg')
    dot.attr(rankdir='TB')
    dot.attr(size="3,3!")
    dot.attr('node', shape="none", margin='0.1,0.1')
    dot.attr('edge', arrowsize='0.5', penwidth='0.7')

    added_nodes = set()    #
    
    for rel in relations:
        for cat_id, cat_name, cat_photo in [
            (rel['catA_id'], rel['catA_name'], rel['catA_photo']),
            (rel['catB_id'], rel['catB_name'], rel['catB_photo'])
        ]:
            if cat_name not in added_nodes:
                photo_url = cat_photos.get(cat_name)
                photo_filename = os.path.basename(photo_url) 
                photo_path = os.path.join(current_app.static_folder, 'uploads', photo_filename)
                label = f'''<   
                <TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0">
                <TR><TD FIXEDSIZE="TRUE" WIDTH="50" HEIGHT="50"><IMG SRC="{photo_path}" SCALE="TRUE"/></TD></TR>
                <TR><TD HEIGHT="30">{cat_name}</TD></TR>
                </TABLE>
                >'''
                dot.node(cat_name, label=label)  # Add cat to the graph with label (relationship type)
                added_nodes.add(cat_name)  # Mark this cat as added

        edge_attrs = {'label': rel['relation_type']}  # Set the label for the relationship

        direction = rel['direction']
        if direction == 'forward':
            edge_attrs['dir'] = 'forward'   # Arrow points from A to B (A → B)
            dot.edge(rel['catA_name'], rel['catB_name'], **edge_attrs) 
        else:
            edge_attrs['dir'] = 'both'   # Double arrows on both ends (A ↔ B)
            dot.edge(rel['catA_name'], rel['catB_name'], **edge_attrs)

    # Save the generated graph as an SVG file in the 'graphs' directory
    output_dir = os.path.join(current_app.static_folder, 'graphs')
    os.makedirs(output_dir, exist_ok=True)  # Ensure the output directory exists
    output_path = os.path.join(output_dir, filename)  # Complete output path for the graph
    dot.render(output_path, format='svg', cleanup=False)   # Render the graph as SVG

    # Open and modify the SVG content to fix the path for images
    svg_file = f"{output_path}.svg"
    with open(svg_file, "r", encoding="utf-8") as f:
        svg_content = f.read()

    # Replace local paths with correct static URL for the images
    svg_content = re.sub(
        r'xlink:href="[^"]*uploads[\\/]',
        'xlink:href="/static/uploads/',
        svg_content
    )
    
    # Write the updated SVG content back to the file
    with open(svg_file, "w", encoding="utf-8") as f:
        f.write(svg_content)

    return url_for('static', filename=f'graphs/{filename}.svg')  # Return the path to the image for html usage


@relationship_bp.route('/relationship_feature', methods=['GET', 'POST'])
def relationship_feature():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Fetch all cats from the database
    all_cats = cursor.execute("SELECT id, name, gender, photo FROM profiles ORDER BY name ASC").fetchall()

    cat_photos = get_cat_photos(all_cats)           
    if len(all_cats) >= 5:
        random_cats = random.sample(all_cats, 5)
    else:
        random_cats = all_cats
        
    if request.method == 'POST':
        if not current_user.is_authenticated:    # Ensure user is logged in when adding relationship
            flash("You must be logged in to add relationship!", category="error")
            return redirect(url_for('auth.login'))
        
        action = request.form.get('action')    # Get the action from the form
        if action == 'add':
            catA_id = request.form.get('catA_id')
            catB_id = request.form.get('catB_id')
            relation_type = request.form.get('relation_type')
            other_relation = request.form.get('other_relation')
            direction = request.form.get('direction')

            # If 'Other' is selected, use the custom relation type
            if relation_type == 'Other' and other_relation and other_relation.strip():
                relation_type = other_relation.strip()

            # Check if the both cat are same
            if catA_id == catB_id:
                flash("Cat A and Cat B cannot be the same!", category="error")
                return redirect(url_for('relationship.relationship_feature'))
            
            # Check if the relationship already exists
            existing_relation = cursor.execute("""
                SELECT COUNT(*) FROM cat_relationship
                WHERE (catA_id = ? AND catB_id = ? AND relation_type = ? AND direction = ?)
                OR (catA_id = ? AND catB_id = ? AND relation_type = ? AND direction = ?)
            """, (catA_id, catB_id, relation_type, direction, catB_id, catA_id, relation_type, direction)).fetchone()[0]

            if existing_relation > 0:
                flash("Looks like someone else already added this relationship!", category="error")
                return redirect(url_for('relationship.relationship_feature'))   
                     
            # Check if the relationship more than 30        
            catA_relations = cursor.execute("""
                SELECT COUNT(*) FROM cat_relationship
                WHERE (catA_id = ? OR catB_id = ?) 
            """, (catA_id, catA_id)).fetchone()[0]

            catB_relations = cursor.execute("""
                SELECT COUNT(*) FROM cat_relationship
                WHERE (catA_id = ? OR catB_id = ?) 
            """, (catB_id, catB_id)).fetchone()[0]

            if catA_relations >= 30 or catB_relations >= 30:
                flash("Each cat can only have a maximum of 30 relationships.", category="error")
                return redirect(url_for('relationship.relationship_feature'))

            # Insert data if valid
            if catA_id and catB_id and relation_type and catA_id != catB_id:
                cursor.execute(
                    "INSERT INTO cat_relationship (catA_id, catB_id, relation_type, direction, user_id) VALUES (?, ?, ?, ?, ?)",
                    (catA_id, catB_id, relation_type, direction, current_user.id)
                )
                conn.commit()
                return redirect(url_for('relationship.relationship_feature'))
        
        elif action == 'edit':
            rel_id = request.form.get('rel_id')
            catA_id = request.form.get('catA_id')
            catB_id = request.form.get('catB_id')
            relation_type = request.form.get('relation_type')
            other_relation = request.form.get('other_relation')
            direction = request.form.get('direction')

            # If 'Other' is selected, use the custom relation type.
            if relation_type == 'Other' and other_relation.strip():
                relation_type = other_relation.strip()

            if rel_id and catA_id and catB_id and relation_type and catA_id != catB_id:
                cursor.execute(
                    "UPDATE cat_relationship SET catA_id=?, catB_id=?, relation_type=?, direction=? WHERE id=?",
                    (catA_id, catB_id, relation_type, direction, rel_id)
                )
                conn.commit()
            return redirect(url_for('relationship.relationship_feature'))

        elif action == 'delete':
            rel_id = request.form.get('rel_id')
            if rel_id:
                cursor.execute("DELETE FROM cat_relationship WHERE id = ?", (rel_id,))
                conn.commit()
            return redirect(url_for('relationship.relationship_feature'))

    if current_user.is_authenticated:
        relations = cursor.execute("""
            SELECT rel.id, rel.catA_id, rel.catB_id, rel.relation_type, rel.direction,
                p1.name AS catA_name, p1.photo AS catA_photo,
                p2.name AS catB_name, p2.photo AS catB_photo
            FROM cat_relationship rel
            JOIN profiles p1 ON rel.catA_id = p1.id
            JOIN profiles p2 ON rel.catB_id = p2.id
            WHERE rel.user_id = ?
        """, (current_user.id,)).fetchall()
    else:
        relations = []

    graph_svg = generate_graph(relations, cat_photos)

    return render_template(
        'relationship_manager.html',
        user=current_user,
        random_cats=random_cats,
        all_cats=all_cats,
        relations=relations,
        tree_img=graph_svg,
    )    


# Whole graph
@relationship_bp.route('/graph', methods=['GET', 'POST'])
def view_graph():
    conn = get_db_connection()
    cursor = conn.cursor()

    cat_filter_name = request.form.get('cat_filter_name', '')
    all_cats = cursor.execute("SELECT id, name, gender, photo FROM profiles ORDER BY name ASC").fetchall()
    cat_photos = get_cat_photos(all_cats)

    relations = cursor.execute("""
        SELECT rel.id, rel.catA_id, rel.catB_id, rel.relation_type, rel.direction,
            p1.name AS catA_name, p1.photo AS catA_photo,
            p2.name AS catB_name, p2.photo AS catB_photo
        FROM cat_relationship rel
        JOIN profiles p1 ON rel.catA_id = p1.id
        JOIN profiles p2 ON rel.catB_id = p2.id
        WHERE p1.name = ? OR p2.name = ?
    """, (cat_filter_name, cat_filter_name)).fetchall()

    if len(relations) > 0:
        graph_svg = generate_graph(relations, cat_photos)
        no_relation_msg = ""
    else:
        graph_svg = ""
        no_relation_msg = "No relationships found, start creating now!"
    
#action for admin
    action = request.form.get('action')
    if action == 'edit':
        rel_id = request.form.get('rel_id')
        catA_id = request.form.get('catA_id')
        catB_id = request.form.get('catB_id')
        relation_type = request.form.get('relation_type')
        other_relation = request.form.get('other_relation')
        direction = request.form.get('direction')

        if relation_type == 'Other' and other_relation and other_relation.strip():
            relation_type = other_relation.strip()

        if rel_id and catA_id and catB_id and relation_type and catA_id != catB_id:
            cursor.execute(
                "UPDATE cat_relationship SET catA_id=?, catB_id=?, relation_type=?, direction=? WHERE id=?",
                (catA_id, catB_id, relation_type, direction, rel_id)
            )
            conn.commit()
        return redirect(url_for('relationship.view_graph', cat_filter_name=cat_filter_name))

    elif action == 'delete':
        rel_id = request.form.get('rel_id')
        if rel_id:
            cursor.execute("DELETE FROM cat_relationship WHERE id = ?", (rel_id,))
            conn.commit()
        return redirect(url_for('relationship.view_graph', cat_filter_name=cat_filter_name))

    return render_template(
        'relationship_viewer.html', 
        user=current_user, 
        all_cats=all_cats,
        relations=relations,
        tree_img=graph_svg,
        cat_filter_name=cat_filter_name,
        no_relation_msg=no_relation_msg
        )