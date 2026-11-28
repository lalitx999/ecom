import re

from django import forms
from django.contrib.auth import get_user_model, password_validation

from shop.forms import StyledFormMixin
from shop.text import make_slug, unique_slug  # noqa: F401 (re-exported)
from shop.models import Brand, Carrier, Category, Order, Page, Product, ProductImage, ProductVariant, ShopSettings

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


class ProductForm(StyledFormMixin, forms.ModelForm):
    brand_name = forms.CharField(label='แบรนด์', max_length=100, required=False,
                                 widget=forms.TextInput(attrs={'list': 'brand-options', 'autocomplete': 'off'}),
                                 help_text='พิมพ์ชื่อแบรนด์ ถ้ายังไม่มีระบบจะสร้างให้')
    expiry_date = forms.DateField(label='วันหมดอายุ (เดือน/ปี)', required=False, input_formats=['%Y-%m', '%Y-%m-%d'],
                                  widget=forms.DateInput(attrs={'type': 'month'}, format='%Y-%m'))

    class Meta:
        model = Product
        fields = ['name', 'category', 'description', 'set_contents', 'how_to_use', 'origin', 'expiry_date',
                  'is_active', 'is_new', 'is_best_seller', 'is_featured', 'slug']
        widgets = {'description': forms.Textarea(attrs={'rows': 6}),
                   'set_contents': forms.Textarea(attrs={'rows': 4}),
                   'how_to_use': forms.Textarea(attrs={'rows': 4})}
        labels = {'slug': 'ชื่อใน URL'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.brand_id:
            self.initial.setdefault('brand_name', self.instance.brand.name)
        self.fields['slug'].required = False
        self.fields['slug'].help_text = 'เว้นว่างเพื่อให้ระบบสร้างจากชื่อสินค้าให้อัตโนมัติ'
        self.fields['category'].empty_label = 'เลือกหมวดหมู่'
        self._style()

    def clean_slug(self):
        return unique_slug(Product, self.cleaned_data.get('slug') or self.data.get('name', ''), self.instance, 'product')

    def save(self, commit=True):
        name = self.cleaned_data.get('brand_name', '').strip()
        if name:
            brand = Brand.objects.filter(name__iexact=name).first()
            if brand is None:
                brand = Brand.objects.create(name=name, slug=unique_slug(Brand, name, None, 'brand'))
            self.instance.brand = brand
        else:
            self.instance.brand = None
        return super().save(commit)


class VariantForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ProductVariant
        fields = ['color', 'size', 'sku', 'price', 'compare_price', 'stock', 'ready_to_ship', 'is_active', 'sort_order']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['price'].widget.attrs.update(min='0', step='0.01')
        self.fields['compare_price'].widget.attrs.update(min='0', step='0.01')
        self.fields['stock'].widget.attrs.update(min='0')
        self.fields['sort_order'].widget.attrs.update(min='0')
        self.fields['sku'].widget.attrs.update(placeholder='อัตโนมัติ')
        self._style()

    def clean_price(self):
        price = self.cleaned_data['price']
        if price is not None and price <= 0:
            raise forms.ValidationError('ราคาต้องมากกว่า 0')
        return price

    def clean(self):
        data = super().clean()
        price, compare = data.get('price'), data.get('compare_price')
        if price and compare and compare <= price:
            self.add_error('compare_price', 'ราคาปกติต้องมากกว่าราคาขาย (หรือเว้นว่างถ้าไม่ลดราคา)')
        data['color'] = (data.get('color') or '').strip()
        data['size'] = (data.get('size') or '').strip()
        return data


class ImageForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ProductImage
        fields = ['image', 'color', 'sort_order']
        widgets = {'image': forms.FileInput(attrs={'accept': 'image/jpeg,image/png,image/webp'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['sort_order'].widget.attrs.update(min='0')
        self._style()

    def clean_image(self):
        img = self.cleaned_data.get('image')
        if img and hasattr(img, 'size') and img.size > MAX_IMAGE_BYTES:
            raise forms.ValidationError('ไฟล์รูปต้องไม่เกิน 5 MB')
        return img


class BaseVariantFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        alive = [f for f in self.forms if f.cleaned_data and not f.cleaned_data.get('DELETE')]
        if not alive:
            raise forms.ValidationError('ต้องมีตัวเลือกสินค้าอย่างน้อย 1 รายการ (สินค้าที่ไม่มีสี/ไซซ์ให้เว้นสองช่องนั้นว่าง)')
        seen = set()
        for f in alive:
            key = (f.cleaned_data.get('color', ''), f.cleaned_data.get('size', ''))
            if key in seen:
                f.add_error('size', 'สีและไซซ์นี้ซ้ำกับแถวอื่น')
            seen.add(key)


VariantFormSet = forms.inlineformset_factory(Product, ProductVariant, form=VariantForm, formset=BaseVariantFormSet,
                                             extra=1, can_delete=True)
ImageFormSet = forms.inlineformset_factory(Product, ProductImage, form=ImageForm, extra=2, can_delete=True)


class ShopSettingsForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ShopSettings
        exclude = ['updated_at']
        widgets = {'address': forms.Textarea(attrs={'rows': 3}),
                   'logo': forms.FileInput(attrs={'accept': 'image/png,image/jpeg,image/webp'}),
                   'favicon': forms.FileInput(attrs={'accept': 'image/png,image/jpeg'})}

    remove_logo = forms.BooleanField(label='ลบโลโก้ (กลับไปใช้ชื่อร้านเป็นตัวอักษร)', required=False)
    remove_favicon = forms.BooleanField(label='ลบไอคอนแท็บ', required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ('shipping_fee', 'free_shipping_threshold'):
            self.fields[name].widget.attrs.update(min='0', step='1')
        self.fields['promptpay_id'].widget.attrs.update(inputmode='numeric')
        self._style()

    def _image(self, name):
        img = self.cleaned_data.get(name)
        if img and hasattr(img, 'size') and img.size > MAX_IMAGE_BYTES:
            raise forms.ValidationError('ไฟล์รูปต้องไม่เกิน 5 MB')
        return img

    def clean_logo(self):
        return self._image('logo')

    def clean_favicon(self):
        return self._image('favicon')

    def clean_promptpay_id(self):
        value = re.sub(r'[\s-]', '', self.cleaned_data['promptpay_id'])
        if value and not re.fullmatch(r'0\d{9}|\d{13}|\d{15}', value):
            raise forms.ValidationError('ใส่เบอร์มือถือ 10 หลัก เลขประจำตัวประชาชน/ผู้เสียภาษี 13 หลัก หรือ e-Wallet 15 หลัก')
        return value

    def clean_bank_account_number(self):
        return self.cleaned_data['bank_account_number'].strip()

    def clean(self):
        data = super().clean()
        bank = [data.get(f) for f in ('bank_name', 'bank_account_number', 'bank_account_name')]
        if any(bank) and not all(bank):
            self.add_error('bank_account_name' if not bank[2] else 'bank_account_number' if not bank[1] else 'bank_name',
                           'กรอกธนาคาร เลขที่บัญชี และชื่อบัญชีให้ครบทั้งสามช่อง')
        for name in ('shipping_fee', 'free_shipping_threshold'):
            if data.get(name) is not None and data[name] < 0:
                self.add_error(name, 'ต้องไม่ติดลบ')
        return data

    def save(self, commit=True):
        obj = super().save(commit=False)
        if self.cleaned_data.get('remove_logo') and not self.files.get('logo'):
            obj.logo = ''
        if self.cleaned_data.get('remove_favicon') and not self.files.get('favicon'):
            obj.favicon = ''
        if commit:
            obj.save()
        return obj


class PageForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Page
        fields = ['title', 'slug', 'body', 'is_published', 'show_in_footer', 'order']
        widgets = {'body': forms.Textarea(attrs={'rows': 18})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['slug'].required = False
        self.fields['slug'].help_text = 'เว้นว่างเพื่อสร้างจากหัวข้อ | หน้า "terms" และ "privacy-policy" จะต้องติ๊กยอมรับตอนสมัครสมาชิกเมื่อเผยแพร่'
        self._style()

    def clean_slug(self):
        return unique_slug(Page, self.cleaned_data.get('slug') or self.data.get('title', ''), self.instance, 'page')


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
