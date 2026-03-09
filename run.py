from app import create_app
from app.routes.public import public_bp

app = create_app()

if __name__ == '__main__':
    app.run(debug=True, port=5000)