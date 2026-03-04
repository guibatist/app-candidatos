from flask import Blueprint, render_template, session, redirect, url_for
from ..services.crm_service import CRMService

crm_bp = Blueprint('crm', __name__)

@crm_bp.route('/')
def dashboard_index():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    cliente_id = session.get('cliente_id')
    resumo = CRMService.get_dashboard_data(cliente_id)
    return render_template('crm/dashboard.html', resumo=resumo)