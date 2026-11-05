import gradio as gr

from ..config import ASSETS


def mount_ui(app, config):
    with gr.Blocks(title="XFlog — X Follower Log", analytics_enabled=False) as ui:
        gr.HTML(
            (ASSETS / "shell.html").read_text(),
            apply_default_css=False,
            js_on_load=(ASSETS / "app.js").read_text(),
            elem_id="xflog-root",
        )
    return gr.mount_gradio_app(
        app,
        ui,
        path="/",
        server_name=config.host,
        footer_links=[],
        css_paths=[
            ASSETS / name
            for name in (
                "app.css",
                "panels.css",
                "timeline.css",
                "constellation.css",
                "settings.css",
                "responsive.css",
                "activity-hud.css",
                "follow-actions.css",
                "interactions.css",
            )
        ],
        favicon_path=str(ASSETS / "mark.svg"),
        head='<link rel="stylesheet" href="/static/xf/fonts.css">',
        show_error=False,
        ssr_mode=False,
        enable_monitoring=False,
    )
