"""
URL Configuration for the Story Generator API.

This module defines the URL patterns for the API endpoints.
"""

from django.urls import path
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)
from .views import (
    StoryListCreateAPIView, StoryDetailAPIView, StorySegmentAPIView,
    SceneListCreateAPIView, SceneDetailAPIView,
    MediaListCreateAPIView, MediaDetailAPIView,
    UserListCreateAPIView, UserDetailAPIView, CurrentUserAPIView,
    UserRegistrationAPIView, UserLoginAPIView, StoryPreviewView,
    PreviewStatusView, RevisionListAPIView, RevisionCurrentAPIView,
    RevisionHistoryAPIView
    # GoogleLogin
)

urlpatterns = [
    # Story endpoints
    path('stories/', StoryListCreateAPIView.as_view(), name='story-list-create'),
    path('stories/<int:pk>/', StoryDetailAPIView.as_view(), name='story-detail'),
    path('stories/<int:pk>/segment/', StorySegmentAPIView.as_view(), name='story-segment'),
    path('stories/<int:pk>/generate-bulk-image/', StoryDetailAPIView.as_view(), name='story-generate-bulk-image'),
    path('stories/<int:pk>/generate-bulk-audio/', StoryDetailAPIView.as_view(), name='story-generate-bulk-audio'),

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
    # path('auth/google/', GoogleLogin.as_view(), name='google-login'),
    path('auth/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    # Preview endpoints
    path('stories/<int:story_id>/preview-pdf/', StoryPreviewView.as_view(), name='story-preview-pdf'),
    path('stories/<int:story_id>/preview-audio/', StoryPreviewView.as_view(), name='story-preview-audio'),
    path('stories/<int:story_id>/preview-video/', StoryPreviewView.as_view(), name='story-preview-video'),
    path('stories/<int:story_id>/preview-status/<str:pk>/', PreviewStatusView.as_view(), name='preview-status'),

    # Revision endpoints
    path('stories/<int:story_id>/revisions/', RevisionListAPIView.as_view(), name='revision-list'),
    path('stories/<int:story_id>/revisions/current/', RevisionCurrentAPIView.as_view(), name='revision-current'),
    path('stories/<int:story_id>/revisions/history/', RevisionHistoryAPIView.as_view(), name='revision-history'),
]