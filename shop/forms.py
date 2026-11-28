import re

from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.forms import AuthenticationForm

from .models import Order

User = get_user_model()


class StyledFormMixin:
    def _style(self):
        for f in self.fields.values():
            w = f.widget
            if isinstance(w, forms.RadioSelect):
                cls = 'form-check-input'
            elif isinstance(w, forms.CheckboxInput):
                cls = 'form-check-input'
            elif isinstance(w, forms.Select):
                cls = 'form-select'
            else:
                cls = 'form-control'
            w.attrs['class'] = (w.attrs.get('class', '') + ' ' + cls).strip()


class LoginForm(StyledFormMixin, AuthenticationForm):
    username = forms.CharField(label='อีเมลหรือชื่อผู้ใช้', widget=forms.TextInput(attrs={'autofocus': True, 'autocomplete': 'username'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['password'].label = 'รหัสผ่าน'
        self._style()

    def clean(self):
        from .ratelimit import LOGIN_WINDOW, login_blocked
        if login_blocked(self.request, self.data.get('username', '')):
            raise forms.ValidationError(
                f'ใส่รหัสผ่านผิดหลายครั้งเกินไป กรุณารอ {LOGIN_WINDOW // 60} นาทีแล้วลองใหม่ หรือกด "ลืมรหัสผ่าน"', code='rate_limited')
        return super().clean()



class RegisterForm(StyledFormMixin, forms.Form):
    full_name = forms.CharField(label='ชื่อ-นามสกุล', max_length=150)
    email = forms.EmailField(label='อีเมล', widget=forms.EmailInput(attrs={'autocomplete': 'email'}))
    password1 = forms.CharField(label='รหัสผ่าน', strip=False, widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))
    password2 = forms.CharField(label='ยืนยันรหัสผ่าน', strip=False, widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))

    def __init__(self, *args, policy_pages=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.policy_pages = list(policy_pages)
        if self.policy_pages:  # only ask once the shop has published its terms / privacy policy
            self.fields['accept_terms'] = forms.BooleanField(
                label='ยอมรับ' + ' และ '.join(p.title for p in self.policy_pages),
                error_messages={'required': 'กรุณายอมรับเงื่อนไขก่อนสมัครสมาชิก'})
        self._style()

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(username__iexact=email).exists():
            raise forms.ValidationError('อีเมลนี้ถูกใช้สมัครแล้ว')
        return email

    def clean(self):
        data = super().clean()
        p1, p2 = data.get('password1'), data.get('password2')
        if p1 and p2:
            if p1 != p2:
                self.add_error('password2', 'รหัสผ่านทั้งสองช่องไม่ตรงกัน')
            else:
                try:
                    password_validation.validate_password(p1)
                except forms.ValidationError as e:
                    self.add_error('password1', e)
        return data

    def save(self):
        d = self.cleaned_data
        return User.objects.create_user(username=d['email'], email=d['email'], password=d['password1'], first_name=d['full_name'])


class CheckoutForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Order
        fields = ['full_name', 'phone', 'address', 'province', 'postal_code', 'note', 'payment_method']
        widgets = {
            'address': forms.Textarea(attrs={'rows': 3}),
            'payment_method': forms.RadioSelect,
            'phone': forms.TextInput(attrs={'inputmode': 'tel', 'autocomplete': 'tel'}),
            'postal_code': forms.TextInput(attrs={'inputmode': 'numeric', 'maxlength': 5, 'autocomplete': 'postal-code'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['payment_method'].choices = Order.Payment.choices
        self.fields['note'].required = False
        self._style()

    def clean_phone(self):
        phone = re.sub(r'[\s-]', '', self.cleaned_data['phone'])
        if not re.fullmatch(r'0\d{8,9}', phone):
            raise forms.ValidationError('กรอกเบอร์โทรศัพท์ไทย 9-10 หลัก เช่น 0812345678')
        return phone

    def clean_postal_code(self):
        code = self.cleaned_data['postal_code'].strip()
        if not re.fullmatch(r'\d{5}', code):
            raise forms.ValidationError('รหัสไปรษณีย์ต้องเป็นตัวเลข 5 หลัก')
        return code


from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm  # noqa: E402

MAX_SLIP_BYTES = 5 * 1024 * 1024


class SlipForm(forms.Form):
    slip = forms.ImageField(label='สลิปโอนเงิน', widget=forms.FileInput(attrs={'accept': 'image/jpeg,image/png,image/webp', 'class': 'form-control'}))

    def clean_slip(self):
        img = self.cleaned_data['slip']
        if img.size > MAX_SLIP_BYTES:
            raise forms.ValidationError('ไฟล์ต้องไม่เกิน 5 MB')
        if getattr(img, 'image', None) is None or img.image.format not in ('JPEG', 'PNG', 'WEBP'):
            raise forms.ValidationError('รองรับเฉพาะไฟล์ JPG, PNG หรือ WebP')
        return img


class ResetRequestForm(StyledFormMixin, PasswordResetForm):
    email = forms.EmailField(label='อีเมลที่ใช้สมัคร', widget=forms.EmailInput(attrs={'autocomplete': 'email', 'autofocus': True}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class NewPasswordForm(StyledFormMixin, SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['new_password1'].label = 'รหัสผ่านใหม่'
        self.fields['new_password2'].label = 'ยืนยันรหัสผ่านใหม่'
        self.fields['new_password1'].help_text = ''
        self._style()
