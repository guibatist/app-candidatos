from flask import Blueprint, render_template, session, redirect, url_for

public_bp = Blueprint('public', __name__)

@public_bp.route('/')
def index():
    """
    Rota Raiz: Entrega o Site Institucional.
    Se o usuário já estiver logado, oferecemos o redirecionamento 
    automático para o ambiente dele (UX de conveniência).
    """
    return render_template('public/landing.html')

# No futuro, você pode adicionar /termos-de-uso ou /privacidade aqui.