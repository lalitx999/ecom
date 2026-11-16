from django.urls import path

from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.home, name='home'),
    path('products/', views.product_list, name='products'),
    path('products/new/', views.product_form, name='product_new'),
    path('products/<int:pk>/edit/', views.product_form, name='product_edit'),
    path('products/<int:pk>/delete/', views.product_delete, name='product_delete'),
    path('products/<int:pk>/quick/', views.product_quick, name='product_quick'),
    path('categories/', views.category_list, name='categories'),
    path('categories/new/', views.category_form, name='category_new'),
    path('categories/<int:pk>/edit/', views.category_form, name='category_edit'),
    path('categories/<int:pk>/delete/', views.category_delete, name='category_delete'),
    path('orders/', views.order_list, name='orders'),
    path('orders/<str:number>/', views.order_detail, name='order_detail'),
    path('orders/<str:number>/confirm-payment/', views.order_confirm_payment, name='order_confirm_payment'),
    path('orders/<str:number>/resend-shipping/', views.order_resend_shipping, name='order_resend_shipping'),
    path('users/', views.user_list, name='users'),
    path('users/new/', views.user_form, name='user_new'),
    path('users/<int:pk>/edit/', views.user_form, name='user_edit'),
    path('users/<int:pk>/password/', views.user_password, name='user_password'),
    path('users/<int:pk>/delete/', views.user_delete, name='user_delete'),
    path('reports/', views.report, name='reports'),
]
