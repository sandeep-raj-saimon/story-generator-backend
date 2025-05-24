"""
Views for the Story Generator API.

This module contains APIViews that handle API requests for users, stories, scenes, and media.
Each view class provides specific endpoints for its respective model.
"""

from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework import permissions, status
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, IsAdminUser
import redis
import os
import json
import razorpay
import uuid
# from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
# from allauth.socialaccount.providers.oauth2.client import OAuth2Client
# from dj_rest_auth.registration.views import SocialLoginView
from .models import Story, Scene, Media, Revision
from .serializers import *
from django.contrib.auth import get_user_model
import json
from openai import OpenAI
from django.conf import settings
import os
from rest_framework import viewsets
from rest_framework.decorators import action
import boto3
from io import BytesIO
import requests
from datetime import datetime, timedelta
from django.db import transaction
from django.db.models import Q

User = get_user_model()

# Initialize Redis client
redis_client = redis.Redis(
    host=os.getenv('REDISHOST'),
    port=os.getenv('REDISPORT'),
    password=os.getenv('REDISPASSWORD')
)

# Default pricing configurations
DEFAULT_PRICING = {
    'com': {
        'currency': '$',
        'plans': [
            {
                'id': 4,
                'name': 'Studio',
                'price': 29.99,
                'credits': 7500,
                'features': [
                    '7500 credits',
                    'Image and Audio generation',
                    'Export to PDF and Mp3 formats'
                ]
            },
            {
                'id': 3,
                'name': 'Pro',
                'price': 14.99,
                'credits': 3000,
                'features': [
                    '3000 credits',
                    'Image and Audio generation',
                    'Export to PDF and Mp3 formats'
                ]
            },
            {
                'id': 2,
                'name': 'Standard',
                'price': 4.99,
                'credits': 1000,
                'features': [
                    '1000 credits',
                    'Only Image generation',
                    'Export to PDF format'
                ]
            },
            {
                'id': 1,
                'name': 'Free',
                'price': 0,
                'credits': 300,
                'features': [
                    '300 credits per month',
                    'Basic story creation'
                ]
            }
        ]
    },
    'in': {
        'currency': '₹',
        'plans': [
            {
                'id': 4,
                'name': 'Studio',
                'price': 499,
                'credits': 7500,
                'features': [
                    '7500 credits',
                    'Image and Audio generation',
                    'Export to PDF and Mp3 formats'
                ]
            },
            {
                'id': 3,
                'name': 'Premium',
                'price': 249,
                'credits': 3000,
                'features': [
                    '3000 credits',
                    'Image and Audio generation',
                    'Export to PDF and Mp3 formats'
                ]
            },
            {
                'id': 2,
                'name': 'Standard',
                'price': 99,
                'credits': 1000,
                'features': [
                    '1000 credits',
                    'Only Image generation',
                    'Export to PDF format'
                ]
            },
            {
                'id': 1,
                'name': 'Free',
                'price': 0,
                'credits': 300,
                'features': [
                    '300 credits per month',
                    'Basic story creation'
                ]
            }
        ]
    }
}

class PricingConfigView(APIView):
    """
    API endpoint for managing pricing configurations.
    
    GET /pricing/config/ - Get pricing configuration for a domain
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        """Get pricing configuration for the current domain."""
        domain = request.query_params.get('domain', 'com')
        if not domain:
            return Response({'error': 'Domain is required'}, status=400)

        # Try to get pricing from Redis
        pricing_key = f'pricing:{domain}'
        pricing_data = redis_client.get(pricing_key)

        if pricing_data:
            return Response(json.loads(pricing_data))
        
        # If not in Redis, use default pricing
        if domain in DEFAULT_PRICING:
            # Store in Redis for future use
            redis_client.set(pricing_key, json.dumps(DEFAULT_PRICING[domain]))
            return Response(DEFAULT_PRICING[domain])
        
        # If domain not found, return .com pricing
        return Response(DEFAULT_PRICING['com'])

class PricingConfigUpdateView(APIView):
    """
    API endpoint for updating pricing configurations.
    
    POST /pricing/config/update/ - Update pricing configuration for a domain (admin only)
    """
    permission_classes = [permissions.IsAdminUser]

    def post(self, request):
        """Update pricing configuration for a domain (admin only)."""
        domain = request.data.get('domain')
        pricing = request.data.get('pricing')

        if not domain or not pricing:
            return Response({'error': 'Domain and pricing are required'}, status=400)

        pricing_key = f'pricing:{domain}'
        redis_client.set(pricing_key, json.dumps(pricing))
        
        return Response({'message': 'Pricing configuration updated successfully'})

class StoryListCreateAPIView(APIView):
    """
    API endpoint for listing and creating stories.
    
    GET /stories/ - List all stories for the current user
    POST /stories/ - Create a new story
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        """List all stories for the current user."""
        stories = Story.objects.filter(author=request.user, is_active=True)
        serializer = StorySerializer(stories, many=True)
        return Response(serializer.data)

    def post(self, request):
        """Create a new story."""
        serializer = StoryCreateSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save(author=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class StoryDetailAPIView(APIView):
    """
    API endpoint for retrieving, updating and deleting a story.
    
    GET /stories/{id}/ - Retrieve a story
    PUT /stories/{id}/ - Update a story
    PATCH /stories/{id}/ - Partially update a story
    DELETE /stories/{id}/ - Delete a story
    POST /stories/{id}/generate-bulk-image/ - Generate images for all scenes
    """
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self, pk):
        """Get story object or return 404."""
        return get_object_or_404(Story, pk=pk, author=self.request.user)

    def get(self, request, pk):
        """Retrieve a story."""
        story = self.get_object(pk)
        serializer = StorySerializer(story)
        return Response(serializer.data)

    def put(self, request, pk):
        """Update a story."""
        story = self.get_object(pk)
        serializer = StorySerializer(story, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request, pk):
        """Partially update a story."""
        story = self.get_object(pk)
        if not story.is_active:
            return Response(
                {"error": "Story is not active and cannot be updated"},
                status=status.HTTP_400_BAD_REQUEST
            )
        story.is_active = False
        story.save()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def delete(self, request, pk):
        """Delete a story."""
        story = self.get_object(pk)
        story.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def post(self, request, pk):
        """Generate image/audio for all scenes in the story."""
        print("Generating images for all scenes in the story.", request.data)
        story = self.get_object(pk)
        voice_id = request.data.get('voice_id')
        url_name = request.resolver_match.url_name
        media_type = url_name.split('-')[-1]
        scenes = story.scenes.all()
        scene_ids = [scene.id for scene in scenes]
        try:
            # Initialize SQS client
            sqs_client = boto3.client(
                'sqs',
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_S3_REGION_NAME
            )
                    
            if media_type == 'image':
                # incase of image, we can send independent messages for each scene
                for scene in scenes:
                    # Prepare the message
                    message = {
                        'story_id': story.id,
                        'voice_id': voice_id,
                        'scene_id': scene.id,
                        'media_type': media_type,
                        'action': 'generate_media'
                    }
                    print(f"Message for media generation: {message}")
                    # Send message to SQS queue
                    response = sqs_client.send_message(
                        QueueUrl=settings.STORY_GENERATION_QUEUE_URL,
                        MessageBody=json.dumps(message)
                    )
            elif media_type == 'audio':
                # incase of audio, we have to single message for all scenes
                message = {
                    'user_id': request.user.id,
                    'story_id': story.id,
                    'voice_id': voice_id,
                    'media_type': media_type,
                    'action': 'generate_entire_audio'
                }
                response = sqs_client.send_message(
                    QueueUrl=settings.STORY_GENERATION_QUEUE_URL,
                    MessageBody=json.dumps(message)
                )
            # Update old media to inactive
            Media.objects.filter(story_id=story.id, scene_id__in=scene_ids, is_active=True, media_type=media_type).update(is_active=False)
            return Response({
                'message': 'Media generation request sent successfully',
                'message_id': response['MessageId']
            })
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class StorySegmentAPIView(APIView):
    """
    API endpoint for segmenting a story.
    
    POST /stories/{id}/segment/ - Segment a story into scenes
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        """Segment a story into scenes."""
        story = get_object_or_404(Story, pk=pk, author=request.user)
        
        try:
            client = OpenAI(
                api_key=settings.CHATGPT_OPENAI_API_KEY
            )
            
            # Prepare the prompt for segmentation
            prompt = f"""
            Segment the following story into logical scenes. For each scene, provide:
            1. A title
            2. The scene content, which should be part of the story content
            3. A highly detailed visual description of the scene, including:
               - Physical setting and environment (indoor/outdoor, time of day, weather, etc.)
               - Background elements and surroundings (buildings, nature, furniture, etc.)
               - Lighting conditions and atmosphere
               - Any notable sounds or ambient noise
               - Character positions, expressions, and clothing
               - Important objects and their placement
               - Color schemes and textures
               - Camera angle/perspective for the scene
               - Any special effects or unique visual elements
            4. The order number
            5. The dominant emotion (e.g., happy, tense, sad, hopeful)
            Story: {story.content}
            
            Format the response as JSON with the following structure:
            {{
                "scenes": [
                    {{
                        "title": "Scene title",
                        "content": "Scene content",
                        "scene_description": "Brief description",
                        "emotion": ["emotion1", "emotion2", "emotion3" and so on],
                        "order": 1
                    }},
                    ...
                ]
            }}
            """
            
            # Call ChatGPT API
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a story segmentation assistant. Break stories into logical scenes. You must respond with valid JSON only."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                response_format={ "type": "json_object" }
            )
            
            # Debug the response
            print("Raw response:", response.choices[0].message.content)
            
            # Parse the response
            try:
                segments = json.loads(response.choices[0].message.content)
            except json.JSONDecodeError as e:
                print("JSON parsing error:", e)
                print("Response content:", response.choices[0].message.content)
                return Response(
                    {"error": "Failed to parse AI response", "details": str(e)},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
            # Create scenes in the database
            created_scenes = []
            for scene_data in segments['scenes']:
                scene = Scene.objects.create(
                    story=story,
                    title=scene_data['title'],
                    content=scene_data['content'],
                    scene_description=scene_data['scene_description'],
                    order=scene_data['order'],
                    emotion=scene_data['emotion']
                )
                created_scenes.append(SceneSerializer(scene).data)
            
            return Response({
                "message": "Story successfully segmented",
                "scenes": created_scenes
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            print("Error:", str(e))
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class SceneListCreateAPIView(APIView):
    """
    API endpoint for listing and creating scenes.
    
    GET /stories/{story_id}/scenes/ - List all scenes for a story
    POST /stories/{story_id}/scenes/ - Create a new scene
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, story_pk):
        """List all scenes for a story."""
        scenes = Scene.objects.filter(story_id=story_pk, story__author=request.user, is_active=True)
        serializer = SceneSerializer(scenes, many=True)
        return Response(serializer.data)

    def post(self, request, story_pk):
        """Create a new scene."""
        story = get_object_or_404(Story, pk=story_pk, author=request.user)
        serializer = SceneSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(story=story)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class SceneDetailAPIView(APIView):
    """
    API endpoint for retrieving, updating and deleting a scene.
    
    GET /stories/{story_id}/scenes/{id}/ - Retrieve a scene
    PUT /stories/{story_id}/scenes/{id}/ - Update a scene
    PATCH /stories/{story_id}/scenes/{id}/ - Partially update a scene
    DELETE /stories/{story_id}/scenes/{id}/ - Delete a scene
    POST /stories/{story_id}/scenes/{id}/generate-image/ - Generate an image for the scene
    POST /stories/{story_id}/scenes/{id}/generate-audio/ - Generate an audio for the scene
    """
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self, story_pk, pk):
        """Get scene object or return 404."""
        return get_object_or_404(
            Scene,
            pk=pk,
            story_id=story_pk,
            story__author=self.request.user
        )

    def get(self, request, story_pk, pk):
        """Retrieve a scene."""
        scene = self.get_object(story_pk, pk)
        serializer = SceneSerializer(scene)
        return Response(serializer.data)

    def put(self, request, story_pk, pk):
        """Update a scene."""
        scene = self.get_object(story_pk, pk)
        serializer = SceneSerializer(scene, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request, story_pk, pk):
        """Partially update a scene."""
        scene = self.get_object(story_pk, pk)
        serializer = SceneSerializer(scene, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, story_pk, pk):
        """Delete a scene."""
        scene = self.get_object(story_pk, pk)
        scene.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def post(self, request, story_pk, pk):
        # return Response({'error': 'Invalid endpoint'}, status=status.HTTP_400_BAD_REQUEST)
        """Generate media for the scene."""
        # Get the URL pattern name to determine which endpoint was called
        url_name = request.resolver_match.url_name
        media_type = url_name.split('-')[-1]
        if url_name == 'scene-generate-image' or url_name == 'scene-generate-audio':
            sqs_client = boto3.client(
                'sqs',
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_S3_REGION_NAME
            )
            
            # Prepare the message
            message = {
                'story_id': story_pk,
                'scene_id': pk,
                'media_type': 'image' if url_name == 'scene-generate-image' else 'audio',
                'action': 'generate_media'
            }
            
            # Add voice_id for audio generation
            if url_name == 'scene-generate-audio':
                try:
                    voice_id = request.data.get('voice_id')
                    if not voice_id:
                        return Response(
                            {'error': 'voice_id is required for audio generation'},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                    # check for previous and next media of the story, order by scene_id
                    # Get previous and next media ordered by scene_id
                    previous_request_ids = list(Media.objects.filter(
                        story_id=story_pk,
                        scene_id__lt=pk,
                        media_type='audio',
                        is_active=True
                    ).order_by('scene__id').values_list('request_id', flat=True))
                    
                    next_request_ids = list(Media.objects.filter(
                        story_id=story_pk,
                        scene_id__gt=pk,
                        media_type='audio',
                        is_active=True
                    ).order_by('scene__id').values_list('request_id', flat=True))
                    
                    message['previous_request_ids'] = previous_request_ids if previous_request_ids else None
                    message['next_request_ids'] = next_request_ids if next_request_ids else None
                    message['voice_id'] = voice_id
                except Exception as e:
                    return Response(
                        {'error': f'Error processing request data: {str(e)}'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            print(message)
            # Send message to SQS queue
            response = sqs_client.send_message(
                QueueUrl=settings.STORY_GENERATION_QUEUE_URL,
                MessageBody=json.dumps(message)
            )
            Media.objects.filter(story_id=story_pk, scene_id=pk, media_type=media_type, is_active=True).update(is_active=False)
            return Response({
                'message': 'Media generation request sent successfully',
                'message_id': response['MessageId']
            })
        else:
            return Response(
                {'error': 'Invalid endpoint'},
                status=status.HTTP_400_BAD_REQUEST
            )

    def _generate_image(self, story_pk, pk):
        """Generate an image for the scene."""
        try:
            # Initialize SQS client
            sqs_client = boto3.client(
                'sqs',
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_S3_REGION_NAME
            )
            
            # Prepare the message
            message = {
                'story_id': story_pk,
                'scene_id': pk,
                'media_type': 'image',
                'action': 'generate_media'
            }
            
            # Send message to SQS queue
            response = sqs_client.send_message(
                QueueUrl=settings.STORY_GENERATION_QUEUE_URL,
                MessageBody=json.dumps(message)
            )
            
            return Response({
                'message': 'Media generation request sent successfully',
                'message_id': response['MessageId']
            })
            
        except Exception as e:
            print(e)
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _generate_audio(self, story_pk, pk):
        """Generate an audio for the scene."""
        try:
            # TODO: Implement audio generation logic
            return Response(
                {'error': 'Audio generation not implemented yet'},
                status=status.HTTP_501_NOT_IMPLEMENTED
            )
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class MediaListCreateAPIView(APIView):
    """
    API endpoint for listing and creating media.
    
    GET /scenes/{scene_id}/media/ - List all media for a scene
    POST /scenes/{scene_id}/media/ - Create new media
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, scene_pk):
        """List all media for a scene."""
        media = Media.objects.filter(scene_id=scene_pk, scene__story__author=request.user)
        serializer = MediaSerializer(media, many=True)
        return Response(serializer.data)

    def post(self, request, scene_pk):
        """Create new media."""
        scene = get_object_or_404(
            Scene,
            pk=scene_pk,
            story__author=request.user
        )
        serializer = MediaSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(scene=scene)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class MediaDetailAPIView(APIView):
    """
    API endpoint for retrieving, updating and deleting media.
    
    GET /scenes/{scene_id}/media/{id}/ - Retrieve media
    PUT /scenes/{scene_id}/media/{id}/ - Update media
    PATCH /scenes/{scene_id}/media/{id}/ - Partially update media
    DELETE /scenes/{scene_id}/media/{id}/ - Delete media
    """
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self, scene_pk, pk):
        """Get media object or return 404."""
        return get_object_or_404(
            Media,
            pk=pk,
            scene_id=scene_pk,
            scene__story__author=self.request.user
        )

    def get(self, request, scene_pk, pk):
        """Retrieve media."""
        media = self.get_object(scene_pk, pk)
        serializer = MediaSerializer(media)
        return Response(serializer.data)

    def put(self, request, scene_pk, pk):
        """Update media."""
        media = self.get_object(scene_pk, pk)
        serializer = MediaSerializer(media, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request, scene_pk, pk):
        """Partially update media."""
        media = self.get_object(scene_pk, pk)
        serializer = MediaSerializer(media, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, scene_pk, pk):
        """Delete media."""
        media = self.get_object(scene_pk, pk)
        media.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class UserListCreateAPIView(APIView):
    """
    API endpoint for listing and creating users.
    
    GET /users/ - List all users
    POST /users/ - Create a new user
    """
    def get_permissions(self):
        """Set permissions based on the request method."""
        if self.request.method == 'POST':
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    def get(self, request):
        """List all users."""
        users = User.objects.all()
        serializer = UserSerializer(users, many=True)
        return Response(serializer.data)

    def post(self, request):
        """Create a new user."""
        serializer = UserRegistrationSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class UserDetailAPIView(APIView):
    """
    API endpoint for retrieving, updating and deleting a user.
    
    GET /users/{id}/ - Retrieve a user
    PUT /users/{id}/ - Update a user
    PATCH /users/{id}/ - Partially update a user
    DELETE /users/{id}/ - Delete a user
    """
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self, pk):
        """Get user object or return 404."""
        return get_object_or_404(User, pk=pk)

    def get(self, request, pk):
        """Retrieve a user."""
        user = self.get_object(pk)
        serializer = UserSerializer(user)
        return Response(serializer.data)

    def put(self, request, pk):
        """Update a user."""
        user = self.get_object(pk)
        serializer = UserSerializer(user, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request, pk):
        """Partially update a user."""
        user = self.get_object(pk)
        serializer = UserSerializer(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        """Delete a user."""
        user = self.get_object(pk)
        user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class CurrentUserAPIView(APIView):
    """
    API endpoint for getting the current user's details.
    
    GET /users/me/ - Get current user's details
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        """Get current user's details."""
        serializer = UserSerializer(request.user)
        return Response(serializer.data)

@method_decorator(csrf_exempt, name='dispatch')
class UserRegistrationAPIView(APIView):
    """
    API endpoint for user registration.
    
    POST /auth/register/ - Register a new user
    """
    permission_classes = [permissions.AllowAny]
    def post(self, request):
        """Register a new user."""
        serializer = UserRegistrationSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            
            # Generate tokens
            refresh = RefreshToken.for_user(user)
            
            return Response({
                'user': UserSerializer(user).data,
                'refresh': str(refresh),
                'access': str(refresh.access_token),
            }, status=status.HTTP_201_CREATED)
        print(serializer.errors)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@method_decorator(csrf_exempt, name='dispatch')
class UserLoginAPIView(APIView):
    """
    API endpoint for user login.
    
    POST /auth/login/ - Login a user
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        """Login a user."""
        email = request.data.get('email')
        password = request.data.get('password')

        if not email or not password:
            return Response(
                {'error': 'Please provide both email and password'},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = authenticate(email=email, password=password)
        
        if not user:
            return Response(
                {'error': 'Invalid credentials'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # Generate tokens
        refresh = RefreshToken.for_user(user)
        
        return Response({
            'user': UserSerializer(user).data,
            'refresh': str(refresh),
            'access': str(refresh.access_token),
        })

class StoryViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=True, methods=['post'], url_path='generate-bulk-image')
    def generate_bulk_image(self, request, pk=None):
        story = self.get_object()
        scenes = story.scenes.all()
        
        try:
            # Initialize S3 client
            s3_client = boto3.client(
                's3',
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_S3_REGION_NAME
            )
            
            # Initialize OpenAI client
            client = OpenAI(api_key=settings.CHATGPT_OPENAI_API_KEY)
            
            for scene in scenes:
                # Generate image using OpenAI's DALL-E
                response = client.images.generate(
                    model="dall-e-3",
                    prompt=f"Generate a detailed, high-quality image for this scene: {scene.content}",
                    size="1024x1024",
                    quality="standard",
                    n=1,
                    response_format="url"
                )
                
                # Get the image URL from OpenAI
                image_url = response.data[0].url
                
                # Download the image
                image_response = requests.get(image_url)
                image_data = BytesIO(image_response.content)
                
                # Generate a unique filename
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f"story_{story.id}/scene_{scene.id}/image_{timestamp}.png"
                
                # Upload to S3
                s3_client.upload_fileobj(
                    image_data,
                    settings.AWS_STORAGE_BUCKET_NAME,
                    filename,
                    ExtraArgs={'ACL': 'public-read'}
                )
                
                # Create S3 URL
                s3_url = f"https://{settings.AWS_S3_CUSTOM_DOMAIN}/{filename}"
                
                # Create a new Media instance for the generated image
                media = Media.objects.create(
                        scene=scene,
                        media_type='image',
                        url=s3_url,
                        description=f"AI-generated image for scene: {scene.title}"
                    )
            
            return Response({'message': 'Images generated successfully for all scenes'})
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class SceneViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=True, methods=['post'], url_path='generate-image')
    def generate_image(self, request, pk=None):
        scene = self.get_object()
        
        try:
            # Initialize S3 client
            s3_client = boto3.client(
                's3',
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_S3_REGION_NAME
            )

            # Initialize OpenAI client
            client = OpenAI(
                api_key=settings.CHATGPT_OPENAI_API_KEY
            )
            # Generate image using OpenAI's DALL-E
            response = client.images.generate(
                model="dall-e-3",
                prompt=f"Generate a detailed, high-quality image for this scene: {scene.content}",
                size="1024x1024",
                quality="standard",
                n=1,
                response_format="url"
            )
            
            # Get the image URL from OpenAI
            image_url = response.data[0].url
            
            # Download the image
            image_response = requests.get(image_url)
            image_data = BytesIO(image_response.content)
            
            # Generate a unique filename
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"story_{scene.story.id}/scene_{scene.id}/image_{timestamp}.png"
            
            # Upload to S3
            bucket_name = settings.IMAGE_AWS_STORAGE_BUCKET_NAME
            s3_client.upload_fileobj(
                image_data,
                settings.AWS_STORAGE_BUCKET_NAME,
                filename,
                ExtraArgs={'ACL': 'public-read'}
            )
            
            # Create S3 URL
            s3_url = f"https://{settings.AWS_S3_CUSTOM_DOMAIN}/{filename}"
            
            # Create a new Media instance for the generated image
            media = Media.objects.create(
                    scene=scene,
                    media_type='image',
                    url=s3_url,
                    description=f"AI-generated image for scene: {scene.title}"
                )
            return Response(MediaSerializer(media).data)
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class StoryPreviewView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, story_id):
        try:
            # if the number of media is not equal to the number of scenes, return an error
            story = Story.objects.get(id=story_id, author=request.user)
            url_name = request.resolver_match.url_name
            format = url_name.split('-')[2]
            format = 'image' if format == 'pdf' else 'audio' if format == 'audio' else 'video' if format == 'video' else 'media'
            
            if story.scenes.count() != story.media.filter(media_type=format, is_active=True).count():
                return Response(
                    {'error': 'generate images for all scenes first'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            # Initialize SQS client
            sqs_client = boto3.client(
                'sqs',
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_S3_REGION_NAME
            )
            
            # Prepare the message
            message = {
                'story_id': story_id,
                'user_id': request.user.id,
                'action': 'generate_pdf_preview' if url_name == 'story-preview-pdf' else 'generate_audio_preview' if url_name == 'story-preview-audio' else 'generate_video_preview' if url_name == 'story-preview-video' else 'generate_media'
            }
            
            # Send message to SQS queue
            response = sqs_client.send_message(
                QueueUrl=settings.STORY_GENERATION_QUEUE_URL,
                MessageBody=json.dumps(message)
            )
            
            return Response({
                'message': 'PDF generation request sent successfully',
                'message_id': response['MessageId']
            })
            
        except Story.DoesNotExist:
            return Response(
                {'error': 'Story not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class PreviewStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, story_id, pk):
        try:
            # Get the latest revision for the story
            revision = Revision.objects.filter(
                story_id=story_id,
                story__author=request.user,
                format=pk
            ).order_by('-created_at').first()
            format = 'mp3' if pk == 'audio' else 'mp4' if pk == 'video' else pk
            if not revision:
                return Response({
                    'status': 'pending'
                })
            
            # Check if preview exists in S3
            s3_client = boto3.client(
                's3',
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_S3_REGION_NAME
            )
            
            bucket_name = settings.PDF_AWS_STORAGE_BUCKET_NAME
            prefix = f"story_{story_id}/preview_{revision.id}.{format}"

            # List objects in S3 with the prefix
            response = s3_client.list_objects_v2(
                Bucket=bucket_name,
                Prefix=prefix
            )
            
            if 'Contents' in response:
                return Response({
                    'status': 'complete',
                    'url': revision.url,
                    'format': revision.format,
                    'created_at': revision.created_at
                })
            
            return Response({
                'status': 'pending'
            })
            
        except Story.DoesNotExist:
            return Response({
                'error': 'Story not found'
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            print(e)
            return Response({
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class RevisionListAPIView(APIView):
    """
    API endpoint for listing and creating revisions.
    
    GET /stories/{story_id}/revisions/ - List all revisions for a story
    POST /stories/{story_id}/revisions/ - Create a new revision
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, story_id):
        """List all revisions for a story."""
        revisions = Revision.objects.filter(story_id=story_id, story__author=request.user)
        serializer = RevisionSerializer(revisions, many=True)
        return Response(serializer.data)

    def post(self, request, story_id):
        """Create a new revision."""
        story = get_object_or_404(Story, id=story_id, author=request.user)
        serializer = RevisionSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(story=story, created_by=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class RevisionCurrentAPIView(APIView):
    """
    API endpoint for getting current revisions.
    
    GET /stories/{story_id}/revisions/current/ - Get current revisions for a story
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, story_id):
        """Get current revisions for a story."""
        revisions = Revision.objects.filter(
            story_id=story_id,
            story__author=request.user,
            is_current=True
        )
        serializer = RevisionSerializer(revisions, many=True)
        return Response(serializer.data)

class RevisionHistoryAPIView(APIView):
    """
    API endpoint for getting revision history.
    
    GET /stories/{story_id}/revisions/history/ - Get revision history for a story
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, story_id):
        """Get revision history for a story."""
        format = request.query_params.get('format')
        revisions = Revision.objects.filter(story_id=story_id, story__author=request.user)
        if format:
            revisions = revisions.filter(format=format)
        serializer = RevisionSerializer(revisions, many=True)
        return Response(serializer.data)

class GeneratedContentListAPIView(APIView):
    """
    API endpoint for listing all generated content across stories.
    
    GET /generated-content/ - List all generated content for the current user
    Query Parameters:
        - page: Page number (default: 1)
        - page_size: Items per page (default: 10)
        - search: Search term for filtering by name or story title
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        """List all generated content for the current user."""
        # Get query parameters
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 10))
        search = request.query_params.get('search', '')

        # Get all stories by the current user
        stories = Story.objects.filter(author=request.user)
        
        # Get all revisions for these stories
        revisions = Revision.objects.filter(story__in=stories).select_related('story')
        
        # Apply search filter if provided
        if search:
            revisions = revisions.filter(
                Q(story__title__icontains=search) |
                Q(format__icontains=search)
            )
        
        # Calculate pagination
        total_count = revisions.count()
        start = (page - 1) * page_size
        end = start + page_size
        
        # Get paginated revisions
        paginated_revisions = revisions[start:end]
        
        # Format the response
        content_list = []
        for revision in paginated_revisions:
            content_list.append({
                'id': revision.id,
                'name': f"{revision.story.title} - {revision.format}",
                'type': revision.format,
                'url': revision.url,
                'createdAt': revision.created_at,
                'size': revision.metadata.get('size', 0) if revision.metadata else 0,
                'storyId': revision.story.id,
                'storyTitle': revision.story.title
            })
        
        return Response({
            'results': content_list,
            'total': total_count,
            'page': page,
            'page_size': page_size,
            'total_pages': (total_count + page_size - 1) // page_size
        })

class ProfileAPIView(APIView):
    """
    API endpoint for getting user profile information.
    
    GET /profile/ - Get user profile information
"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        """Get user profile information."""
        serializer = UserSerializer(request.user)
        return Response(serializer.data)
    
class CreateOrderView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        """Create an order."""
        plan_id = request.query_params.get('plan_id')
        if plan_id is None or plan_id == '' or plan_id == '1':
            return Response({'error': 'Invalid plan'}, status=status.HTTP_400_BAD_REQUEST)
        domain = request.query_params.get('domain')
        if domain == 'in':
            currency = 'INR'
        else:
            currency = 'USD'
        plans = DEFAULT_PRICING[domain]['plans']
        print(plans, plan_id, domain)
        plan = next((p for p in plans if p['id'] == int(plan_id)), None)
        if not plan:
            return Response({'error': 'Invalid plan'}, status=status.HTTP_400_BAD_REQUEST)
        amount = plan['price']
        receipt = redis_client.incr('prod_razorpay_last_order_id') if redis_client.get('is_razorpay_test') else redis_client.incr('prod_razorpay_last_order_id')
        print(amount, currency, receipt)

        client = razorpay.Client(auth=(settings.TEST_RAZORPAY_KEY_ID, settings.TEST_RAZORPAY_KEY_SECRET)) if redis_client.get('is_razorpay_test') else razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
        order_params = {
            'amount': amount*100,
            'currency': currency,
            'receipt': f'order_rcptid_{receipt}',
            'notes': []
        }
        print(order_params)
        order = client.order.create(order_params)
        order_obj = OrderSerializer(data={'user': request.user.id, 'amount': amount, 'status': 'pending', 'order_id': order['id']})
        if order_obj.is_valid():
            order_obj.save()
            return Response(order_obj.data, status=status.HTTP_201_CREATED)
        else:
            return Response(order_obj.errors, status=status.HTTP_400_BAD_REQUEST)
    
class PaymentView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        """Create a payment."""
        client = razorpay.Client(auth=(settings.TEST_RAZORPAY_KEY_ID, settings.TEST_RAZORPAY_KEY_SECRET))
        request.body = request.data

        is_verified= client.utility.verify_payment_signature({
        'razorpay_order_id': request.data.get('order_id'),
        'razorpay_payment_id': request.data.get('razorpay_payment_id'),
        'razorpay_signature': request.data.get('razorpay_signature')
        })

        if is_verified:
            try:
                with transaction.atomic():
                    order = Order.objects.get(order_id=request.data.get('order_id'))
                    order.status = 'paid'
                    order.save()

                    credit_to_be_added = next(p for p in DEFAULT_PRICING[request.query_params.get('domain')]['plans'] if p['id'] == int(request.data.get('plan_id')))['credits']
                    print('credit_to_be_added', credit_to_be_added, request.query_params.get('domain'), request.data.get('plan_id'), DEFAULT_PRICING[request.query_params.get('domain')]['plans'])
                    credits = order.user.credits.filter(is_active=True).first()
                    credits.credits_remaining += credit_to_be_added
                    credits.save()
                    order.user.save()

                    credit_transaction_obj = CreditTransactionSerializer(data={'user': order.user.id, 'credits_used': credit_to_be_added, 'transaction_type': 'credit', 'scene': None})
                    if credit_transaction_obj.is_valid():
                        credit_transaction_obj.save()

                    payment_obj = PaymentSerializer(data={'order': order.id, 'payment_id': request.data.get('razorpay_payment_id'), 'payment_status': 'paid', 'payment_signature': request.data.get('razorpay_signature')})
                    if payment_obj.is_valid():
                        payment_obj.save()
                        return Response({'message': f'{credit_to_be_added} credits added to your account'}, status=status.HTTP_200_OK)
                    else:
                        return Response(payment_obj.errors, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                print('error in payment', e)
                return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response({'error': 'Payment verification failed'}, status=status.HTTP_400_BAD_REQUEST)