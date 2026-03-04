from ..utils.json_helper import filter_by_client

class CRMService:
    @staticmethod
    def get_dashboard_data(cliente_id):
        apoiadores = filter_by_client('apoiadores', cliente_id)
        bairros = {}
        for a in apoiadores:
            bairros[a['bairro']] = bairros.get(a['bairro'], 0) + 1
        return {
            "total_apoiadores": len(apoiadores),
            "bairros": bairros
        }