# NThaCityRP Web System

Roleplay dispatch, CAD, DMV, civilian registry, complaints, BOLO tracking, and Discord-integrated RP management system.

## Features

- Police CAD dashboard
- Civilian registration
- DMV records and licensing
- Applications and complaints
- BOLO management
- Discord webhook integration
- Admin dashboard
- Live city status system

## Stack

- HTML
- CSS
- Vanilla JavaScript
- Python Flask backend
- Gunicorn production server

## Required Environment Variables

- FLASK_SECRET
- ADMIN_PASSWORD

## Optional Environment Variables

- DISCORD_WEBHOOK_URL
- SMTP_HOST
- SMTP_PORT
- SMTP_EMAIL
- SMTP_PASSWORD
- SMTP_FROM_NAME
- NOTIFY_EMAIL

## Local Development

```bash
pip install -r requirements.txt
python server.py
```

## Production Start Command

```bash
gunicorn server:app
```

## Deployment Notes

This repository now includes:

- requirements.txt
- Procfile
- runtime.txt

Compatible with:

- Railway
- Render
- Replit Deployments
- Fly.io
- Generic Gunicorn Python hosting

## Cloudflare Pages Note

Cloudflare Pages alone will not run the Flask backend APIs. Use a Python-capable host for the backend or migrate APIs to Cloudflare Workers.
