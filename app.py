from flask import Flask, render_template, request, redirect, url_for, flash
from flask_pymongo import PyMongo
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from bson import ObjectId
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'hello_world'

app.config["MONGO_URI"] = "mongodb+srv://atharvakantode16:todoproject162004@to-do-cluster.whftpzh.mongodb.net/tododb?retryWrites=true&w=majority&appName=to-do-cluster"
mongo = PyMongo(app)

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

# --- User Model --- #
class User(UserMixin):
    def __init__(self, user_data):
        self.id = str(user_data['_id'])
        self.username = user_data['username']

@login_manager.user_loader
def load_user(user_id):
    user_data = mongo.db.users.find_one({'_id': ObjectId(user_id)})
    if user_data:
        return User(user_data)
    return None

# --- Register --- #
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        if mongo.db.users.find_one({'username': username}):
            flash('Username already exists!', 'danger')
            return redirect(url_for('register'))

        hashed_password = generate_password_hash(password)
        mongo.db.users.insert_one({'username': username, 'password': hashed_password})
        flash('Registered successfully! Please login.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

# --- Login --- #
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user_data = mongo.db.users.find_one({'username': username})
        if user_data and check_password_hash(user_data['password'], password):
            user = User(user_data)
            login_user(user)
            flash('Logged in successfully.', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid credentials.', 'danger')
            return redirect(url_for('login'))

    return render_template('login.html')


@login_manager.unauthorized_handler
def unauthorized_callback():
    # Just redirect silently without flashing
    return redirect(url_for('login'))


# --- Logout --- #
@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# --- Home / To-Do Page --- #
@app.route('/', methods=['GET', 'POST'])
@login_required
def index():
    if request.method == 'POST':
        title = request.form['title']
        desc = request.form['desc']
        todo = {
            'title': title,
            'desc': desc,
            'date_created': datetime.utcnow(),
            'user_id': ObjectId(current_user.id)
        }
        mongo.db.todos.insert_one(todo)
        flash('To-Do added successfully!', 'success')
        return redirect(url_for('index'))

    allToDo = list(mongo.db.todos.find({'user_id': ObjectId(current_user.id)}))
    return render_template('index.html', allToDo=allToDo)

@app.route('/update/<todo_id>', methods=['GET', 'POST'])
@login_required
def update(todo_id):
    todo = mongo.db.todos.find_one({'_id': ObjectId(todo_id), 'user_id': ObjectId(current_user.id)})

    if not todo:
        flash("To-Do not found or unauthorized.", "danger")
        return redirect(url_for('index'))

    if request.method == 'POST':
        title = request.form['title']
        desc = request.form['desc']

        mongo.db.todos.update_one(
            {'_id': ObjectId(todo_id)},
            {'$set': {'title': title, 'desc': desc}}
        )
        flash('To-Do updated successfully!', 'success')
        return redirect(url_for('index'))

    return render_template('update.html', todo=todo)

@app.route('/delete/<todo_id>')
@login_required
def delete(todo_id):
    result = mongo.db.todos.delete_one({'_id': ObjectId(todo_id), 'user_id': ObjectId(current_user.id)})
    if result.deleted_count:
        flash('To-Do deleted successfully.', 'success')
    else:
        flash('To-Do not found or unauthorized.', 'danger')
    return redirect(url_for('index'))

@app.route('/about')
@login_required
def about():
    return render_template('about.html')

@app.route('/contact', methods=['GET', 'POST'])
@login_required
def contact():
    if request.method == 'POST':
        name = request.form['name']
        phone = request.form['phone']
        email = request.form['email']
        query = request.form['query']

        mongo.db.contacts.insert_one({
            'name': name,
            'phone': phone,
            'email': email,
            'query': query,
            'user_id': ObjectId(current_user.id),
            'submitted_at': datetime.utcnow()
        })
        flash('Your query has been submitted!', 'success')
        return redirect(url_for('contact'))

    return render_template('contact.html')


if __name__ == '__main__':
    app.run(debug=True)
