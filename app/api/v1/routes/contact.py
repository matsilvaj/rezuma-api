from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request, status

from app.core.database import get_supabase
from app.core.rate_limit import excedeu
from app.models.schemas import ContactCreate
from app.services.contact_mail import enviar_aviso_contato

router = APIRouter()


def _ip(request: Request) -> str:
    encaminhado = request.headers.get("X-Forwarded-For")
    if encaminhado:
        # Último da cadeia: é o que o proxy do Railway acrescenta, e o cliente
        # não consegue forjar.
        return encaminhado.split(",")[-1].strip()
    return request.client.host if request.client else "desconhecido"


@router.post("/", status_code=status.HTTP_201_CREATED)
def enviar_contato(body: ContactCreate, request: Request):
    """
    Recebe uma mensagem do formulário de contato.

    A mensagem é gravada primeiro e o aviso por e-mail vem depois: se o SMTP
    estiver fora do ar, a mensagem não se perde. O endpoint é público, então
    carrega três travas contra robô e abuso: limite por IP, limite geral e
    um campo isca que só robô preenche.
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

    # Teto geral: um IP só é barrado acima, mas uma botnet distribuída não.
    # Isto limita o estrago a um volume que dá para revisar à mão.
    if excedeu("contato:total", 60, timedelta(hours=1)):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Estamos recebendo muitas mensagens agora. Tente novamente mais tarde.",
        )

    supabase = get_supabase()
    supabase.table("contact_messages").insert({
        "nome": body.nome.strip(),
        "email": str(body.email).strip().lower(),
        "mensagem": body.mensagem.strip(),
        "ip": ip,
    }).execute()

    enviar_aviso_contato(body.nome.strip(), str(body.email), body.mensagem.strip())

    return {"message": "Mensagem recebida."}
