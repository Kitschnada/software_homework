from app import create_app
import os

app = create_app()

if __name__ == '__main__':
    if not os.path.exists(app.config['DATABASE']):
        with app.app_context():
            from app.db import init_db
            init_db()
    app.run(debug=True, port=5000)