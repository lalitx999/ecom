import re
import unicodedata

from django import forms
from django.contrib.auth import get_user_model, password_validation

from shop.forms import StyledFormMixin
from shop.models import Carrier, Category, Order, Product

User = get_user_model()
MAX_IMAGE_BYTES = 5 * 1024 * 1024


class CategoryForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name', 'slug', 'order']
        labels = {'slug': 'ชื่อใน URL'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['slug'].required = False
        self.fields['slug'].help_text = 'เว้นว่างเพื่อให้ระบบสร้างให้อัตโนมัติ'
        self._style()

    def clean_slug(self):
        return unique_slug(Category, self.cleaned_data.get('slug') or self.data.get('name', ''), self.instance, 'category')


def make_slug(text):
    """URL-safe slug that keeps Thai letters and tone marks (Django's slugify() drops the combining marks)."""
    text = unicodedata.normalize('NFC', text).strip().lower()
    text = re.sub(r'[^\w\u0e00-\u0e7f\s-]', '', text)
    return re.sub(r'[-\s]+', '-', text).strip('-_')


def unique_slug(model, source, instance, fallback):
    base = make_slug(source)[:40].strip('-') or fallback
    slug, n = base, 2
    qs = model.objects.exclude(pk=instance.pk)
    while qs.filter(slug=slug).exists():
        slug, n = f'{base}-{n}', n + 1
    return slug


class ProductForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Product
        fields = ['name', 'category', 'brand', 'size', 'description', 'price', 'compare_price', 'stock',
                  'image', 'is_active', 'is_new', 'is_best_seller', 'slug']
        widgets = {'description': forms.Textarea(attrs={'rows': 6}),
                   'image': forms.FileInput(attrs={'accept': 'image/*'})}
        labels = {'slug': 'ชื่อใน URL'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['slug'].required = False
        self.fields['slug'].help_text = 'เว้นว่างเพื่อให้ระบบสร้างจากชื่อสินค้าให้อัตโนมัติ'
        self.fields['price'].widget.attrs.update(min='0', step='0.01')
        self.fields['compare_price'].widget.attrs.update(min='0', step='0.01')
        self.fields['stock'].widget.attrs.update(min='0')
        self.fields['category'].empty_label = 'เลือกหมวดหมู่'
        self._style()

    def clean_price(self):
        price = self.cleaned_data['price']
        if price <= 0:
            raise forms.ValidationError('ราคาต้องมากกว่า 0')
        return price

    def clean_image(self):
        img = self.cleaned_data.get('image')
        if img and hasattr(img, 'size') and img.size > MAX_IMAGE_BYTES:
            raise forms.ValidationError('ไฟล์รูปต้องไม่เกิน 5 MB')
        return img

    def clean_slug(self):
        return unique_slug(Product, self.cleaned_data.get('slug') or self.data.get('name', ''), self.instance, 'product')

    def clean(self):
        data = super().clean()
        price, compare = data.get('price'), data.get('compare_price')
        if price and compare and compare <= price:
            self.add_error('compare_price', 'ราคาปกติต้องมากกว่าราคาขาย (หรือเว้นว่างถ้าไม่ลดราคา)')
        return data


ROLE_CHOICES = [('customer', 'ลูกค้า'), ('staff', 'ผู้ดูแลร้าน'), ('superuser', 'ผู้ดูแลสูงสุด (จัดการผู้ใช้ได้)')]


class UserForm(StyledFormMixin, forms.Form):
    full_name = forms.CharField(label='ชื่อ-นามสกุล', max_length=150)
    email = forms.EmailField(label='อีเมล (ใช้เข้าสู่ระบบ)')
    role = forms.ChoiceField(label='บทบาท', choices=ROLE_CHOICES)
    is_active = forms.BooleanField(label='เปิดใช้งานบัญชี', required=False, initial=True)
    password1 = forms.CharField(label='รหัสผ่าน', strip=False, widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))
    password2 = forms.CharField(label='ยืนยันรหัสผ่าน', strip=False, widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))

    def __init__(self, *args, instance=None, editing_self=False, **kwargs):
        self.instance = instance
        self.editing_self = editing_self
        super().__init__(*args, **kwargs)
        if instance:
            del self.fields['password1'], self.fields['password2']
            self.initial = {
                'full_name': instance.first_name, 'email': instance.email, 'is_active': instance.is_active,
                'role': 'superuser' if instance.is_superuser else 'staff' if instance.is_staff else 'customer',
            }
        if editing_self:  # cannot lock yourself out
            self.fields['role'].disabled = True
            self.fields['is_active'].disabled = True
        self._style()

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        qs = User.objects.filter(username__iexact=email)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('อีเมลนี้ถูกใช้แล้ว')
        return email

    def clean(self):
        data = super().clean()
        if not self.instance:
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
        user = self.instance or User()
        user.username = user.email = d['email']
        user.first_name = d['full_name']
        if not self.editing_self:
            user.is_active = d['is_active']
            user.is_superuser = d['role'] == 'superuser'
            user.is_staff = d['role'] in ('staff', 'superuser')
        if not self.instance:
            user.set_password(d['password1'])
        user.save()
        return user


class SetPasswordForm(StyledFormMixin, forms.Form):
    password1 = forms.CharField(label='รหัสผ่านใหม่', strip=False, widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))
    password2 = forms.CharField(label='ยืนยันรหัสผ่านใหม่', strip=False, widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self._style()

    def clean(self):
        data = super().clean()
        p1, p2 = data.get('password1'), data.get('password2')
        if p1 and p2:
            if p1 != p2:
                self.add_error('password2', 'รหัสผ่านทั้งสองช่องไม่ตรงกัน')
            else:
                try:
                    password_validation.validate_password(p1, self.user)
                except forms.ValidationError as e:
                    self.add_error('password1', e)
        return data


class OrderStatusForm(StyledFormMixin, forms.Form):
    status = forms.ChoiceField(label='สถานะคำสั่งซื้อ', choices=Order.Status.choices)
    carrier = forms.ChoiceField(label='ขนส่ง', choices=[('', 'เลือกขนส่ง')] + list(Carrier.choices), required=False)
    tracking_number = forms.CharField(label='เลขพัสดุ', max_length=40, required=False,
                                      widget=forms.TextInput(attrs={'autocomplete': 'off', 'placeholder': 'เลขที่ได้จากขนส่ง'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()

    def clean_tracking_number(self):
        value = self.cleaned_data['tracking_number'].strip().upper()
        if value and not re.fullmatch(r'[A-Z0-9-]{6,30}', value):
            raise forms.ValidationError('เลขพัสดุต้องเป็นตัวอักษรอังกฤษหรือตัวเลข 6-30 ตัว')
        return value

    def clean(self):
        data = super().clean()
        if data.get('status') == Order.Status.SHIPPED:
            if not data.get('carrier'):
                self.add_error('carrier', 'กรุณาเลือกขนส่ง')
            if not data.get('tracking_number'):
                self.add_error('tracking_number', 'กรุณากรอกเลขพัสดุ')
        return data
