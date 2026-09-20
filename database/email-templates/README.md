# E-mails de autenticação (Supabase)

Estes arquivos são os templates que o Supabase envia. Eles vivem no painel,
não no código, então ficam versionados aqui para não se perderem e para o
histórico de mudanças existir.

Onde colar: **Authentication → Emails**, um arquivo por template. Cole o HTML
inteiro no corpo e ajuste o assunto conforme a tabela.

| Arquivo | Template no painel | Assunto |
|---|---|---|
| `confirmar-cadastro.html` | Confirm sign up | Confirme seu e-mail no Rezuma |
| `redefinir-senha.html` | Reset password | Redefinir sua senha do Rezuma |
| `alterar-email.html` | Change email address | Confirme a troca de e-mail no Rezuma |
| `senha-alterada.html` | Security → Password changed | Sua senha do Rezuma foi alterada |

Não usamos **Magic link / OTP**, **Invite user** nem **Reauthentication**: o
login é por senha e a reautenticação, quando necessária, é feita pedindo a
senha na própria tela. Se um dia passarem a ser usados, os templates padrão
saem em inglês, então precisarão de tradução antes.

## Variáveis

Só use as que o Supabase entrega para cada template. Variável inexistente não
dá erro: aparece escrita no e-mail, em cru.

- `{{ .ConfirmationURL }}`: o link de ação. Usado nos três primeiros.
- `{{ .Email }}` e `{{ .NewEmail }}`: endereço atual e novo, só em Change email.
- `senha-alterada.html` não usa variável nenhuma, de propósito: é um aviso.

## Decisões de conteúdo

- **Sem imagem.** A marca é texto. Cliente de e-mail bloqueia imagem por
  padrão, e um logo que não carrega deixa o e-mail com cara de quebrado.
- **Fundo escuro declarado.** `color-scheme: dark` mais `bgcolor` em cada
  bloco. Sem isso o Gmail assume que o e-mail é claro e aplica a própria
  inversão no modo escuro, devolvendo fundo branco com texto preto.
- **O link aparece escrito**, além do botão. Alguns clientes não renderizam o
  botão, e sem o endereço visível a pessoa fica sem saída.
- **Toda mensagem diz o que acontece se não foi você.** É o que transforma um
  e-mail automático em aviso de segurança útil.

## Configurações que os templates assumem

Em **Authentication → Sign In / Providers → Email**:

- **Confirm email** ligado. Sem isso o cadastro não pede confirmação e o
  primeiro template nunca é enviado.
- **Secure email change** ligado. Com ele, trocar de e-mail exige confirmação
  no endereço antigo e no novo. Sem ele, basta o novo, e quem tomasse uma
  sessão aberta conseguiria migrar a conta para um e-mail próprio.

Em **Authentication → Emails → Security**:

- **Password changed** ligado, que é o gatilho de `senha-alterada.html`.

Depois de colar, envie um teste para si mesmo e confira no celular: é onde o
modo escuro costuma quebrar.
