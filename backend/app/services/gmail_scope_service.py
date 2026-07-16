GMAIL_MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
GMAIL_FULL_ACCESS_SCOPE = "https://mail.google.com/"


def gmail_scope_values(scopes: str | None) -> set[str]:
    return {scope.strip() for scope in str(scopes or "").split() if scope.strip()}


def gmail_scopes_allow_modify(scopes: str | None) -> bool:
    granted = gmail_scope_values(scopes)
    return GMAIL_MODIFY_SCOPE in granted or GMAIL_FULL_ACCESS_SCOPE in granted


def gmail_scopes_with_modify(scopes: str | None) -> str:
    configured = [scope.strip() for scope in str(scopes or "").split() if scope.strip()]
    if not gmail_scopes_allow_modify(scopes):
        configured.append(GMAIL_MODIFY_SCOPE)
    return " ".join(dict.fromkeys(configured))
