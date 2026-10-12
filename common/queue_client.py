import os, json, pika

def _connection():
    creds = pika.PlainCredentials(os.environ["RABBITMQ_USER"], os.environ["RABBITMQ_PASS"])
    return pika.BlockingConnection(
        pika.ConnectionParameters(
            host=os.environ["RABBITMQ_HOST"],
            credentials=creds,
            heartbeat=600,
        )
    )

def declare_topology(ch):
    ch.exchange_declare("conversao.dlx", "direct", durable=True)
    ch.queue_declare("conversao.dlq", durable=True)
    ch.queue_bind("conversao.dlq", "conversao.dlx")
    ch.queue_declare("conversao", durable=True, arguments={
        "x-dead-letter-exchange": "conversao.dlx"
    })
    ch.queue_declare("notificacoes", durable=True)

def get_channel():
    """Abre uma conexão nova e garante que a topologia (filas/exchange) existe."""
    conn = _connection()
    ch = conn.channel()
    declare_topology(ch)
    return conn, ch

def publish_conversion(ch, payload: dict):
    ch.basic_publish("", "conversao", body=json.dumps(payload),
                      properties=pika.BasicProperties(delivery_mode=2))

def publish_notification(ch, payload: dict):
    ch.basic_publish("", "notificacoes", body=json.dumps(payload),
                      properties=pika.BasicProperties(delivery_mode=2))