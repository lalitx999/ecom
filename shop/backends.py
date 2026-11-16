from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailOrUsernameBackend(ModelBackend):
    """Log in with either the username or the e-mail address (case-insensitive).

    Accounts made with `createsuperuser` may have a username that is not an e-mail. An e-mail shared by several
    accounts is ambiguous and is not accepted; the username always works.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()
        username = username if username is not None else kwargs.get(User.USERNAME_FIELD)
        if not username or password is None:
            return None
        username = username.strip()
        user = User.objects.filter(username=username).first() or User.objects.filter(username__iexact=username).first()
        if user is None:
            matches = list(User.objects.filter(email__iexact=username)[:2])
            user = matches[0] if len(matches) == 1 else None
        if user is not None and user.check_password(password) and self.user_can_authenticate(user):
            return user
        User().set_password(password)  # keep timing similar when the account does not exist
        return None
