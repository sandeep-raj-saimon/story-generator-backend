"""
URL Configuration for the WhisprTales API.

This module defines the URL patterns for the API endpoints.
"""

from django.urls import path
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)
from .views import *

urlpatterns = [
    # Story endpoints
    path('stories/', StoryListCreateAPIView.as_view(), name='story-list-create'),
    path('stories/<int:pk>/', StoryDetailAPIView.as_view(), name='story-detail'),
    path('stories/<int:pk>/generate-bulk-image/', StoryDetailAPIView.as_view(), name='story-generate-bulk-image'),
    path('stories/<int:pk>/generate-bulk-audio/', StoryDetailAPIView.as_view(), name='story-generate-bulk-audio'),
    path('stories/generate/', StoryGenerateAPIView.as_view(), name='dummy-story-generate'),
    path('stories/<int:pk>/segment/', StorySegmentAPIView.as_view(), name='story-segment'),
    
    # Public story endpoints (no authentication required)
    path('stories/public/', PublicStoryListAPIView.as_view(), name='public-story-list'),
    path('stories/public/<int:pk>/', PublicStoryDetailAPIView.as_view(), name='public-story-detail'),
    path('stories/public/<int:story_id>/revisions/', PublicStoryRevisionsAPIView.as_view(), name='public-story-revisions'),

    # Scene endpoints
    path('stories/<int:story_pk>/scenes/', SceneListCreateAPIView.as_view(), name='scene-list-create'),
    path('stories/<int:story_pk>/scenes/<int:pk>/', SceneDetailAPIView.as_view(), name='scene-detail'),
    path('stories/<int:story_pk>/scenes/<int:pk>/generate-image/', SceneDetailAPIView.as_view(), name='scene-generate-image'),
    path('stories/<int:story_pk>/scenes/<int:pk>/generate-audio/', SceneDetailAPIView.as_view(), name='scene-generate-audio'),

    # Media endpoints
    path('scenes/<int:scene_pk>/media/', MediaListCreateAPIView.as_view(), name='media-list-create'),
    path('scenes/<int:scene_pk>/media/<int:pk>/', MediaDetailAPIView.as_view(), name='media-detail'),

    # User endpoints
    path('users/', UserListCreateAPIView.as_view(), name='user-list-create'),
    path('users/<int:pk>/', UserDetailAPIView.as_view(), name='user-detail'),
    path('users/me/', CurrentUserAPIView.as_view(), name='current-user'),

    # Authentication endpoints
    path('auth/register/', UserRegistrationAPIView.as_view(), name='user-register'),
    path('auth/login/', UserLoginAPIView.as_view(), name='user-login'),

    # Forgot password endpoints
    path('auth/forgot-password/', ForgotPasswordView.as_view(), name='forgot-passsword'),
    path('auth/reset-password/', ResetPasswordView.as_view(), name='reset-passsword'),
    # path('auth/google/', GoogleLogin.as_view(), name='google-login'),
    path('auth/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    # Verify referral code
    path('auth/validate-referral/', ValidateReferralView.as_view(), name='validate-referral-code'),
    # Preview endpoints
    path('stories/<int:story_id>/preview-pdf/', StoryPreviewView.as_view(), name='story-preview-pdf'),
    path('stories/<int:story_id>/preview-audio/', StoryPreviewView.as_view(), name='story-preview-audio'),
    path('stories/<int:story_id>/preview-video/', StoryPreviewView.as_view(), name='story-preview-video'),
    path('stories/<int:story_id>/preview-voice/', StoryPreviewView.as_view(), name='story-preview-voice'),
    
    path('stories/<int:story_id>/preview-status/<str:pk>/', PreviewStatusView.as_view(), name='preview-status'),

    # Revision endpoints
    path('stories/<int:story_id>/revisions/', RevisionListAPIView.as_view(), name='revision-list'),
    path('stories/<int:story_id>/revisions/current/', RevisionCurrentAPIView.as_view(), name='revision-current'),
    path('stories/<int:story_id>/revisions/history/', RevisionHistoryAPIView.as_view(), name='revision-history'),
    
    # Generated content endpoint
    path('generated-content/', GeneratedContentListAPIView.as_view(), name='generated-content-list'),
    path('generated-content/<int:pk>/', GeneratedContentListAPIView.as_view(), name='update-generated-content'),

    # profile related endpoint
    path('profile/', ProfileAPIView.as_view(), name='profile'),

    # payment related endpoint
    path('pricing/config/', PricingConfigView.as_view(), name='get_pricing_config'),
    path('pricing/config/update/', PricingConfigUpdateView.as_view(), name='update_pricing_config'),    
    path('payment/create-order/', CreateOrderView.as_view(), name='create_order'),
    path('payment/verify/', PaymentView.as_view(), name='verify_payment'),

    # Job endpoints
    path('jobs/', JobViewSet.as_view({'get': 'list', 'post': 'create'}), name='job-list-create'),
    path('jobs/<uuid:pk>/', JobViewSet.as_view({
        'get': 'retrieve',
        'put': 'update',
        'patch': 'partial_update',
        'delete': 'destroy'
    }), name='job-detail'),
    path('jobs/<uuid:pk>/retry/', JobViewSet.as_view({'post': 'retry'}), name='job-retry'),
    path('jobs/<uuid:pk>/cancel/', JobViewSet.as_view({'post': 'cancel'}), name='job-cancel'),
]