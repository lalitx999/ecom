from django.conf import settings
from django.contrib.auth import views as auth_views
from django.urls import path

from . import views
from django.urls import reverse_lazy

from .forms import LoginForm, NewPasswordForm, ResetRequestForm

app_name = 'shop'

urlpatterns = [
    path('', views.home, name='home'),
    path('products/', views.product_list, name='product_list'),
    path('products/<str:slug>/', views.product_detail, name='product_detail'),
    path('cart/', views.cart_page, name='cart'),
    path('cart/add/', views.cart_add, name='cart_add'),
    path('cart/update/', views.cart_update, name='cart_update'),
    path('cart/remove/', views.cart_remove, name='cart_remove'),
    path('checkout/', views.checkout, name='checkout'),
    path('orders/', views.order_list, name='orders'),
    path('orders/<str:number>/', views.order_detail, name='order_detail'),
    path('orders/<str:number>/slip/', views.order_slip, name='order_slip'),
    path('login/', auth_views.LoginView.as_view(template_name='shop/login.html', authentication_form=LoginForm, redirect_authenticated_user=True), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('register/', views.register, name='register'),
    path('pages/<str:slug>/', views.page, name='page'),
    path('password-reset/', views.RateLimitedPasswordResetView.as_view(
        template_name='shop/password_reset_form.html', form_class=ResetRequestForm,
        email_template_name='registration/password_reset_email.txt', subject_template_name='registration/password_reset_subject.txt',
        extra_email_context={'brand': settings.SITE_NAME},
        success_url=reverse_lazy('shop:password_reset_done')), name='password_reset'),
    path('password-reset/sent/', auth_views.PasswordResetDoneView.as_view(template_name='shop/password_reset_done.html'), name='password_reset_done'),
    path('password-reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='shop/password_reset_confirm.html', form_class=NewPasswordForm,
        success_url=reverse_lazy('shop:password_reset_complete')), name='password_reset_confirm'),
    path('password-reset/complete/', auth_views.PasswordResetCompleteView.as_view(template_name='shop/password_reset_complete.html'), name='password_reset_complete'),
]
