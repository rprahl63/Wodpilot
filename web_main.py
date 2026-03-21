"""Flask web application entry point."""
from web.app import create_app
from config import get_config

app = create_app()

if __name__ == "__main__":
    cfg = get_config()
    app.run(host="0.0.0.0", port=cfg.web_port, debug=False)
