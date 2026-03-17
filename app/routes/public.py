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

@public_bp.route('/tecnologia')
def tecnologia():
    # Página detalhando Georreferenciamento e I.A.
    return render_template('public/tecnologia.html')

@public_bp.route('/planos')
def planos():
    # Página de modelos de contratação
    return render_template('public/planos.html')

@public_bp.route('/quem-somos')
def quem_somos():
    # Página institucional e DNA da empresa
    return render_template('public/quem_somos.html')

# No futuro, você pode adicionar /termos-de-uso ou /privacidade aqui.