FROM ghcr.io/open-webui/open-webui:v0.11.4
COPY overlay/index.html /app/build/index.html
COPY overlay/static/ /app/build/static/
# Open WebUI mounts /static from the backend, ahead of the frontend SPA.
COPY overlay/static/ /app/backend/open_webui/static/
