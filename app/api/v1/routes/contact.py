from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request, status

from app.core.rate_limit import excedeu
from app.models.schemas import ContactCreate
from app.services.contact_telegram import enviar_contato

router = APIRouter()

ASSUNTOS = {
    "erro": "Erro em um resumo",
    "sugestao": "Sugestão",
    "duvida": "Dúvida",
    "outro": "Outro assunto",
}


def _ip(request: Request) -> str:
    encaminhado = request.headers.get("X-Forwarded-For")
    if encaminhado:
        # Último da cadeia: é o que o proxy do Railway acrescenta, e o cliente
        # não consegue forjar.
        return encaminhado.split(",")[-1].strip()
    return request.client.host if request.client else "desconhecido"


@router.post("/", status_code=status.HTTP_201_CREATED)
def enviar_mensagem_contato(body: ContactCreate, request: Request):
    """
    Recebe uma mensagem do formulário de contato e entrega para quem mantém.

    Endpoint público, então carrega três travas contra robô e abuso: limite
    por IP, teto geral e um campo isca que só robô preenche.

    Não há banco por trás: se a entrega falhar, a resposta é erro, para a
    pessoa poder tentar de novo em vez de achar que a mensagem chegou.
    """
    if body.website:
        # Campo escondido no formulário. Gente não vê, robô preenche tudo.
        # Responde como se tivesse dado certo para não ensinar o robô.
        return {"message": "Mensagem recebida."}

    ip = _ip(request)
    if excedeu(f"contato:{ip}", 3, timedelta(hours=1)):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Muitas mensagens seguidas. Tente novamente mais tarde.",
        )

    # Um IP só é barrado acima, mas uma botnet distribuída não. Isto limita o
    # estrago a um volume que dá para ler à mão.
    if excedeu("contato:total", 60, timedelta(hours=1)):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Estamos recebendo muitas mensagens agora. Tente novamente mais tarde.",
        )

    entregue = enviar_contato(
        assunto=ASSUNTOS.get(body.assunto, ASSUNTOS["outro"]),
        nome=body.nome.strip(),
        email=str(body.email).strip().lower(),
        mensagem=body.mensagem.strip(),
    )

    if not entregue:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Não foi possível enviar agora. Tente novamente em alguns minutos.",
        )

    return {"message": "Mensagem recebida."}
