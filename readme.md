# Robot_Alertas_Finance_sql

Bot 24/7 para alertas de acciones con:
- Backend Flask + PostgreSQL
- Alertas por precio de **alza** y **baja**
- **Anotaciones** personalizadas por nivel
- Notificaciones vía **Telegram**
- Dashboard web (PWA) con tema oscuro
- Pensado para desplegar en **Render**

## Requisitos

- Python 3.10+
- PostgreSQL (local o Render)
- Variable de entorno `DATABASE_URL` configurada

## Instalación local

```bash
git clone https://github.com/TU_USER/Robot_Alertas_Finance_sql.git
cd Robot_Alertas_Finance_sql
python -m venv venv
source venv/bin/activate  # o venv\Scripts\activate en Windows
pip install -r requirements.txt
