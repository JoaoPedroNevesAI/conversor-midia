import json
from common.queue_client import get_channel
from .mailer import send_email

def process(ch, method, properties, body):
    data = json.loads(body)
    if data["status"] == "CONCLUIDO":
        send_email(data["notifyEmail"], "Sua conversão está pronta",
                    f"Seu arquivo foi convertido: {data['resultUrl']}")
    else:
        send_email(data["notifyEmail"], "Falha na conversão",
                    f"Não foi possível converter seu arquivo: {data.get('error')}")
    ch.basic_ack(method.delivery_tag)

def main():
    conn, ch = get_channel()
    ch.basic_consume("notificacoes", process)
    print("Notifier aguardando eventos...")
    ch.start_consuming()

if __name__ == "__main__":
    main()