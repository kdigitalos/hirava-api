"""Provider delivery for retained mail features. Never claim inbox delivery."""
from email.message import EmailMessage
import logging
import smtplib
import ssl

import httpx
from fastapi import HTTPException


def send_interview(settings, recipients, content):
    if not settings.sendgrid_api_key.get_secret_value() or not settings.sendgrid_verified_sender:
        raise HTTPException(503, 'Interview email is not configured. Contact your administrator.')
    try:
        response = httpx.post('https://api.sendgrid.com/v3/mail/send', timeout=20,
            headers={'Authorization': 'Bearer ' + settings.sendgrid_api_key.get_secret_value()},
            json={'from': {'email': settings.sendgrid_verified_sender}, 'subject': 'Interview Meeting Invitation',
                  'personalizations': [{'to': [{'email': recipient}]} for recipient in recipients],
                  'content': [{'type': 'text/plain', 'value': content}]})
        response.raise_for_status()
    except httpx.HTTPError:
        raise HTTPException(503, 'Email provider did not confirm acceptance. Check delivery logs before retrying.') from None


def smtp_configured(settings):
    return bool(settings.smtp_host and settings.smtp_user and settings.smtp_password.get_secret_value())


def subscription_emails(settings, record):
    if not smtp_configured(settings):
        return
    try:
        factory = smtplib.SMTP_SSL if settings.smtp_port == 465 else smtplib.SMTP
        options = {'context': ssl.create_default_context()} if settings.smtp_port == 465 else {}
        with factory(settings.smtp_host, settings.smtp_port, timeout=20, **options) as smtp:
            if settings.smtp_port != 465:
                smtp.starttls(context=ssl.create_default_context())
            smtp.login(settings.smtp_user, settings.smtp_password.get_secret_value())
            for recipient, subject, content in (
                (record['primaryContactEmail'], 'Hirava subscription request received',
                 f"We received your request for {record['companyName']}. Reference: {record['id']}. The team will contact you."),
                (settings.team_notification_email or settings.smtp_user, 'New Hirava subscription request',
                 f"Reference: {record['id']}\nCompany: {record['companyName']}\nContact: {record['primaryContactName']}\nEmail: {record['primaryContactEmail']}\nProduct: {record['productRequired']}\nPlan: {record['subscriptionPlan']}")):
                message = EmailMessage()
                message['From'] = settings.mail_from or settings.smtp_user
                message['To'], message['Subject'] = recipient, subject
                message.set_content(content)
                smtp.send_message(message)
    except Exception:
        # The lead was committed already. Avoid exposing addresses or credentials.
        logging.getLogger(__name__).warning('Subscription email delivery failed; request remains saved')
