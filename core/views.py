"""
Views for the WhisprTales API.

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
import math
# from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
# from allauth.socialaccount.providers.oauth2.client import OAuth2Client
# from dj_rest_auth.registration.views import SocialLoginView
from .models import Story, Scene, Media, Revision, CreditTransaction, Job
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
from django.http import JsonResponse
from django.core.mail import send_mail
from django.utils.crypto import get_random_string
from django.utils import timezone
import resend
import traceback
from .utils import *
from .utils import send_job_to_sqs

User = get_user_model()

# Initialize Redis client
redis_client = redis.Redis(
    host=os.getenv('REDISHOST'),
    port=os.getenv('REDISPORT'),
    password=os.getenv('REDISPASSWORD')
)

DISCOUNT_PERCENTAGE = 10
REFERRAL_FREE_CREDITS = 300
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
                'price': 1,
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
                        QueueUrl=settings.WHISPR_TALES_QUEUE_URL,
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
                    QueueUrl=settings.WHISPR_TALES_QUEUE_URL,
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
        """Generate media for the scene."""
        url_name = request.resolver_match.url_name
        media_type = url_name.split('-')[-1]
        if url_name == 'scene-generate-image' or url_name == 'scene-generate-audio':
            try:
                # Get user's active credits
                user_credits = request.user.credits.filter(is_active=True).first()
                scene = Scene.objects.filter(id=pk).first()
                if not user_credits:
                    return Response(
                        {'error': 'No active credits found for user'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # Check if user has enough credits
                credit_cost =  math.ceil(CREDIT_COSTS[media_type] if media_type == 'image' else CREDIT_COSTS[media_type] * len(scene.content))
                # Create job record
                job_data = {
                    'job_type': 'generate_media',
                    'user': request.user.id,
                    'story': story_pk,
                    'scene': pk,
                    'request_data': {
                        'story_id': story_pk,
                        'scene_id': pk,
                        'media_type': 'image' if url_name == 'scene-generate-image' else 'audio',
                        'action': 'generate_media',
                        'credit_cost': credit_cost
                    }
                }

                # Add voice_id for audio generation
                if url_name == 'scene-generate-audio':
                    voice_id = request.data.get('voice_id')
                    if not voice_id:
                        return Response(
                            {'error': 'voice_id is required for audio generation'},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                    
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
                    
                    job_data['request_data'].update({
                        'previous_request_ids': previous_request_ids if previous_request_ids else None,
                        'next_request_ids': next_request_ids if next_request_ids else None,
                        'voice_id': voice_id
                    })

                # Create and send job within a transaction
                with transaction.atomic():
                    # Create job
                    serializer = JobCreateSerializer(data=job_data)
                    if serializer.is_valid():
                        job = serializer.save(user=request.user)
                        # Create credit transaction record
                        credit_transaction = CreditTransaction.objects.create(
                            user=request.user,
                            scene=scene,
                            credits_used=credit_cost,
                            transaction_type='debit'
                        )
                        
                        # Link credit transaction to job
                        job.credit_transaction = credit_transaction
                        job.credit_cost = credit_cost
                        job.save()
                        
                        # Find active media records
                        active_media = Media.objects.filter(
                            story_id=story_pk,
                            scene_id=pk,
                            media_type=media_type,
                            is_active=True
                        )
                        print('active_media', active_media, active_media.first())
                        
                        # Get media_id before marking as inactive
                        media_id = active_media[0].id if active_media.exists() else None
                        print('active media is', media_id)
                        
                        # Mark them as inactive
                        active_media.update(is_active=False)
                        
                        try:
                            # Send job to SQS
                            job = send_job_to_sqs(job, job.request_data, media_id)
                            return Response(JobSerializer(job).data)
                        except Exception as e:
                            error_traceback = traceback.format_exc()
                            print(f'Error in media generation:')
                            print(f'Error: {str(e)}')
                            print('Traceback:')
                            print(error_traceback)
                            # The job is already marked as failed in send_job_to_sqs
                            return Response(
                                {
                                    'error': f'Failed to send job to queue: {str(e)}',
                                    'traceback': error_traceback if settings.DEBUG else None
                                },
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR
                            )
                    else:
                        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                error_traceback = traceback.format_exc()
                print(f'Error in media generation:')
                print(f'Error: {str(e)}')
                print('Traceback:')
                print(error_traceback)
                return Response(
                    {
                        'error': str(e),
                        'traceback': error_traceback if settings.DEBUG else None
                    },
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
    def generate_referral_code(self):
        """Generate a unique referral code."""
        while True:
            # Generate a random 8-character code
            code = str(uuid.uuid4())[:8].upper()
            
            # Check if code already exists
            if not User.objects.filter(referral_code=code).exists():
                return code

    permission_classes = [permissions.AllowAny]
    def post(self, request):
        """Register a new user."""
        # Generate referral code before validation
        request.data['referral_code'] = self.generate_referral_code()
        serializer = UserRegistrationSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            # Generate tokens
            refresh = RefreshToken.for_user(user)
            # Create a dummy story by copying story with id=1
            try:
                template_story = Story.objects.get(id=1)
                
                # Create new story with copied data
                Story.objects.create(
                    title=template_story.title,
                    content=template_story.content,
                    author=user,
                    is_public=template_story.is_public,
                    word_count=template_story.word_count,
                    is_default=True
                )

            except Story.DoesNotExist:
                # If template story doesn't exist, continue without creating dummy story
                pass
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
            story = Story.objects.get(id=story_id, author=request.user)
            url_name = request.resolver_match.url_name
            format = url_name.split('-')[2]
            format = 'image' if format == 'pdf' else 'audio' if format == 'audio' else 'video' if format == 'video' else 'media'
            
            if story.scenes.filter(is_active=True).count() != story.media.filter(media_type=format, is_active=True).count():
                return Response(
                    {'error': f'generate {format} for all scenes first'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Create job record
            job_type = {
                'story-preview-pdf': 'generate_pdf_preview',
                'story-preview-audio': 'generate_audio_preview',
                'story-preview-video': 'generate_video_preview'
            }.get(url_name, 'generate_media')

            job_data = {
                'job_type': job_type,
                'user': request.user.id,
                'story': story_id,
                'request_data': {
                    'story_id': story_id,
                    'user_id': request.user.id,
                    'action': job_type
                }
            }

            # Create and send job
            serializer = JobCreateSerializer(data=job_data)
            if serializer.is_valid():
                try:
                    with transaction.atomic():
                        job = serializer.save(user=request.user)
                        
                        # Mark current revision as inactive
                        Revision.objects.filter(
                            story_id=story_id,
                            format=format if format != 'image' else 'pdf',
                            is_active=True,
                            deleted_at=None
                        ).update(is_active=False)
                        
                        # Send job to SQS
                        job = send_job_to_sqs(job, job.request_data)
                        return Response(JobSerializer(job).data)
                except Exception as e:
                    error_traceback = traceback.format_exc()
                    print(f'Error in preview generation:')
                    print(f'Error: {str(e)}')
                    print('Traceback:')
                    print(error_traceback)
                    return Response(
                        {
                            'error': f'Failed to send job to queue: {str(e)}',
                            'traceback': error_traceback if settings.DEBUG else None
                        },
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            
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
                format=pk,
                is_active=True,
                deleted_at=None
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
        revisions = Revision.objects.filter(story__in=stories, deleted_at__isnull=True).select_related('story').order_by('-created_at')
        
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
    def delete(self, request, pk):
        """Delete generated content."""
        if not pk:
            return Response({'error': 'Content ID is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            revision = Revision.objects.get(id=pk, story__author=request.user)
            revision.deleted_at = datetime.now()
            revision.is_active = False
            revision.save()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except Revision.DoesNotExist:
            return Response({'error': 'Content not found'}, status=status.HTTP_404_NOT_FOUND)
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
        print("create order", request.data)
        plan_id = request.query_params.get('plan_id')

        referral_code = request.data.get('referral_code')
        referring_user = None
        if referral_code:
            referring_user = User.objects.filter(referral_code=referral_code).first()

            if not referring_user:
                return Response(
                    {'error': 'Invalid referral code'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Check if code is not user's own referral code
            if referring_user == request.user:
                return Response(
                    {'error': 'Cannot use your own referral code'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        if plan_id is None or plan_id == '' or plan_id == '1':
            return Response({'error': 'Invalid plan'}, status=status.HTTP_400_BAD_REQUEST)
        domain = request.query_params.get('domain')
        if domain == 'in':
            currency = 'INR'
        else:
            currency = 'USD'
        plans = DEFAULT_PRICING[domain]['plans']

        plan = next((p for p in plans if p['id'] == int(plan_id)), None)
        if not plan:
            return Response({'error': 'Invalid plan'}, status=status.HTTP_400_BAD_REQUEST)
        
        amount = round(plan['price'] * (1 - (DISCOUNT_PERCENTAGE) / 100), 2) if referring_user else plan['price']
        receipt = redis_client.incr('prod_razorpay_last_order_id') if redis_client.get('is_razorpay_test') else redis_client.incr('prod_razorpay_last_order_id')

        client = razorpay.Client(auth=(settings.TEST_RAZORPAY_KEY_ID, settings.TEST_RAZORPAY_KEY_SECRET)) if redis_client.get('is_razorpay_test') else razorpay.Client(auth=(settings.PROD_RAZORPAY_KEY_ID, settings.PROD_RAZORPAY_KEY_SECRET))
        order_params = {
            'amount': amount*100,
            'currency': currency,
            'receipt': f'order_rcptid_{receipt}',
            'notes': {
                'referral_code': referral_code
            }
        }
        order = client.order.create(order_params)
        metadata = {
            'referral_code': referral_code
        }
        order_obj = OrderSerializer(data={
            'user': request.user.id,
            'amount': amount,
            'status': 'pending',
            'order_id': order['id'],
            'metadata': metadata
        })
        if order_obj.is_valid():
            order_obj.save()
            return Response(order_obj.data, status=status.HTTP_201_CREATED)
        else:
            return Response(order_obj.errors, status=status.HTTP_400_BAD_REQUEST)
    
def send_payment_success_email(user, order, credit_to_be_added, credits_remaining, domain, referee=None):
    """Send payment success email to user."""
    try:
        resend.api_key = settings.RESEND_KEY
        
        # HTML email template for payment success
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Payment Successful - WhisprTales</title>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    margin: 0;
                    padding: 0;
                }}
                .container {{
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                }}
                .header {{
                    text-align: center;
                    padding: 20px 0;
                    background: linear-gradient(to right, #4f46e5, #7c3aed);
                    border-radius: 8px 8px 0 0;
                }}
                .header h1 {{
                    color: white;
                    margin: 0;
                    font-size: 24px;
                }}
                .content {{
                    background: #ffffff;
                    padding: 30px;
                    border-radius: 0 0 8px 8px;
                    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
                }}
                .success-icon {{
                    text-align: center;
                    margin: 20px 0;
                }}
                .success-icon svg {{
                    width: 64px;
                    height: 64px;
                    color: #10B981;
                }}
                .details {{
                    background: #f8fafc;
                    border-radius: 6px;
                    padding: 20px;
                    margin: 20px 0;
                }}
                .details p {{
                    margin: 10px 0;
                }}
                .footer {{
                    text-align: center;
                    margin-top: 20px;
                    color: #666;
                    font-size: 14px;
                }}
                .button {{
                    display: inline-block;
                    padding: 12px 24px;
                    background: linear-gradient(to right, #4f46e5, #7c3aed);
                    color: white;
                    text-decoration: none;
                    border-radius: 6px;
                    font-weight: 600;
                    margin-top: 20px;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>Payment Successful!</h1>
                </div>
                <div class="content">
                    <div class="success-icon">
                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
                        </svg>
                    </div>
                    
                    <p>Hello {user.username},</p>
                    
                    <p>Thank you for your purchase! Your payment has been successfully processed and your credits have been added to your account.</p>
                    
                    <div class="details">
                        <p><strong>Order Details:</strong></p>
                        <p>Order ID: {order.order_id}</p>
                        <p>Amount Paid: {order.amount} {DEFAULT_PRICING[domain]['currency']}</p>
                        <p>Credits Added: {credit_to_be_added}</p>
                        <p>New Credit Balance: {credits_remaining}</p>
                    </div>
                    
                    <p>You can now use these credits to create amazing stories with WhisprTales. Start your creative journey today!</p>
                    
                    <div style="text-align: center;">
                        <a href="{settings.FRONTEND_URL}" class="button">Start Creating</a>
                    </div>
                    
                    <p>If you have any questions or need assistance, please don't hesitate to contact our support team.</p>
                    
                    <p>Best regards,<br>The WhisprTales Team</p>
                </div>
                <div class="footer">
                    <p>This is an automated message, please do not reply to this email.</p>
                    <p>&copy; {timezone.now().year} WhisprTales. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """

        # Send email using Resend
        r = resend.Emails.send({
            "from": "WhisprTales <support@whisprtales.com>",
            "to": user.email,
            "subject": "Payment Successful - Credits Added to Your Account",
            "html": html_content
        })
        
        print('Payment success email sent:', r)
        return True
    except Exception as e:
        print('Error sending payment success email:', str(e))
        return False

def send_referral_success_email(referee, referred_user):
    """Send email to referee when their referral code is used."""
    try:
        resend.api_key = settings.RESEND_KEY
        
        # HTML email template for referral success
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Referral Success - WhisprTales</title>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    margin: 0;
                    padding: 0;
                }}
                .container {{
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                }}
                .header {{
                    text-align: center;
                    padding: 20px 0;
                    background: linear-gradient(to right, #4f46e5, #7c3aed);
                    border-radius: 8px 8px 0 0;
                }}
                .header h1 {{
                    color: white;
                    margin: 0;
                    font-size: 24px;
                }}
                .content {{
                    background: #ffffff;
                    padding: 30px;
                    border-radius: 0 0 8px 8px;
                    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
                }}
                .success-icon {{
                    text-align: center;
                    margin: 20px 0;
                }}
                .success-icon svg {{
                    width: 64px;
                    height: 64px;
                    color: #10B981;
                }}
                .bonus-section {{
                    background: #f0fdf4;
                    border: 1px solid #bbf7d0;
                    color: #166534;
                    padding: 20px;
                    border-radius: 6px;
                    margin: 20px 0;
                }}
                .details {{
                    background: #f8fafc;
                    border-radius: 6px;
                    padding: 20px;
                    margin: 20px 0;
                }}
                .button {{
                    display: inline-block;
                    padding: 12px 24px;
                    background: linear-gradient(to right, #4f46e5, #7c3aed);
                    color: white;
                    text-decoration: none;
                    border-radius: 6px;
                    font-weight: 600;
                    margin-top: 20px;
                }}
                .footer {{
                    text-align: center;
                    margin-top: 20px;
                    color: #666;
                    font-size: 14px;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>Referral Success!</h1>
                </div>
                <div class="content">
                    <div class="success-icon">
                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
                        </svg>
                    </div>
                    
                    <p>Hello {referee.username},</p>
                    
                    <p>Great news! Your referral code was just used by {referred_user.username} to sign up for WhisprTales.</p>
                    
                    <div class="bonus-section">
                        <p><strong>🎉 You've Earned {REFERRAL_FREE_CREDITS} Free Credits!</strong></p>
                        <p>As a thank you for referring {referred_user.username}, we've added {REFERRAL_FREE_CREDITS} free credits to your account.</p>
                    </div>
                    
                    <div class="details">
                        <p><strong>Your Referral Code:</strong> {referee.referral_code}</p>
                        <p>Share this code with your friends and family to earn more free credits!</p>
                    </div>
                    
                    <p>Keep the referrals coming! For every friend who signs up using your referral code, you'll receive {REFERRAL_FREE_CREDITS} free credits.</p>
                    
                    <div style="text-align: center;">
                        <a href="{settings.FRONTEND_URL}/share" class="button">Share Your Referral Code</a>
                    </div>
                    
                    <p>Thank you for helping us grow the WhisprTales community!</p>
                    
                    <p>Best regards,<br>The WhisprTales Team</p>
                </div>
                <div class="footer">
                    <p>This is an automated message, please do not reply to this email.</p>
                    <p>&copy; {timezone.now().year} WhisprTales. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """

        # Send email using Resend
        r = resend.Emails.send({
            "from": "WhisprTales <support@whisprtales.com>",
            "to": referee.email,
            "subject": "Referral Success - You've Earned Free Credits!",
            "html": html_content
        })
        
        print('Referral success email sent to referee:', r)
        return True
    except Exception as e:
        print('Error sending referral success email:', str(e))
        return False

class PaymentView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        """Create a payment."""
        client = razorpay.Client(auth=(settings.TEST_RAZORPAY_KEY_ID, settings.TEST_RAZORPAY_KEY_SECRET)) if redis_client.get('is_razorpay_test') else razorpay.Client(auth=(settings.PROD_RAZORPAY_KEY_ID, settings.PROD_RAZORPAY_KEY_SECRET))
        request.body = request.data

        is_verified = client.utility.verify_payment_signature({
            'razorpay_order_id': request.data.get('order_id'),
            'razorpay_payment_id': request.data.get('razorpay_payment_id'),
            'razorpay_signature': request.data.get('razorpay_signature')
        })

        if is_verified:
            try:
                # Store data needed for email outside transaction
                email_data = None
                referee = None
                
                # Database operations in transaction
                with transaction.atomic():
                    order = Order.objects.get(order_id=request.data.get('order_id'))
                    order.status = 'paid'
                    order.save()

                    # Get referral code from order metadata
                    order_metadata = order.metadata
                    referral_code = order_metadata.get('referral_code') if order_metadata else None
                    
                    # If there's a valid referral code, update the user's referred_by field
                    if referral_code:
                        referee = User.objects.filter(referral_code=referral_code).first()
                        if referee and referee != order.user:
                            # Update referred_by relationship
                            order.user.referred_by = referee
                            order.user.save()
                            
                            # Add referral bonus credits to the referee (person whose code was used)
                            referee_credits = referee.credits.filter(is_active=True).first()
                            if referee_credits:
                                referee_credits.credits_remaining += REFERRAL_FREE_CREDITS
                                referee_credits.save()
                                
                                # Create credit transaction record for the referee
                                credit_transaction = CreditTransaction.objects.create(
                                    user=referee,  # Changed from order.user to referee
                                    credits_used=REFERRAL_FREE_CREDITS,
                                    transaction_type='credit'
                                )

                    # Add purchased credits to the user who made the payment
                    credit_to_be_added = next(p for p in DEFAULT_PRICING[request.query_params.get('domain')]['plans'] if p['id'] == int(request.data.get('plan_id')))['credits']
                    credits = order.user.credits.filter(is_active=True).first()
                    credits.credits_remaining += credit_to_be_added
                    credits.save()
                    order.user.save()

                    # Create credit transaction for the purchased credits
                    credit_transaction_obj = CreditTransactionSerializer(data={
                        'user': order.user.id,
                        'credits_used': credit_to_be_added,
                        'transaction_type': 'credit',
                        'scene': None
                    })
                    if credit_transaction_obj.is_valid():
                        credit_transaction_obj.save()

                    payment_obj = PaymentSerializer(data={
                        'order': order.id,
                        'payment_id': request.data.get('razorpay_payment_id'),
                        'payment_status': 'paid',
                        'payment_signature': request.data.get('razorpay_signature')
                    })
                    if payment_obj.is_valid():
                        payment_obj.save()
                        # Store data needed for email
                        email_data = {
                            'user': order.user,
                            'order': order,
                            'credit_to_be_added': credit_to_be_added,
                            'credits_remaining': credits.credits_remaining,
                            'domain': request.query_params.get('domain'),
                            'referee': referee
                        }
                    else:
                        return Response(payment_obj.errors, status=status.HTTP_400_BAD_REQUEST)

                # Send emails outside of transaction
                if email_data:
                    # Send payment success email to the user who made the payment
                    send_payment_success_email(
                        email_data['user'],
                        email_data['order'],
                        email_data['credit_to_be_added'],
                        email_data['credits_remaining'],
                        email_data['domain'],
                        email_data['referee']
                    )
                    
                    # Send referral success email to the referee (person whose code was used)
                    if email_data['referee']:
                        send_referral_success_email(email_data['referee'], email_data['user'])

                return Response({'message': f'{credit_to_be_added} credits added to your account'}, status=status.HTTP_200_OK)
                
            except Exception as e:
                print('error in payment:', e)
                return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response({'error': 'Invalid payment signature'}, status=status.HTTP_400_BAD_REQUEST)

class StoryGenerateAPIView(APIView):
    """
    API endpoint for generating a story.
    
    POST /stories/generate/ - Generate a new story
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        """Generate a new story."""
        try:
            # Call OpenAI API to generate story
            client = OpenAI(
                api_key=settings.CHATGPT_OPENAI_API_KEY
            )
            openai_response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a creative story writer. Generate an engaging story of exactly 200 words. Your response must be in JSON format with two fields: 'title' and 'content'. The title should be on a single line, and the content should be the story text."},
                    {"role": "user", "content": "Generate a story in JSON format with 'title' and 'content' fields."}
                ],
                max_tokens=500,
                temperature=0.7,
                response_format={ "type": "json_object" }
            )

            # Extract the response text
            story_text = openai_response.choices[0].message.content
            
            try:
                # Parse the JSON response
                story_data = json.loads(story_text)
                # Deduct credits
                return JsonResponse(story_data)
                
            except json.JSONDecodeError as e:
                error_traceback = traceback.format_exc()
                print(f'Error parsing story generation response:')
                print(f'Error: {str(e)}')
                print('Traceback:')
                print(error_traceback)
                return JsonResponse(
                    {"error": "Failed to parse story generation response",
                     "traceback": error_traceback if settings.DEBUG else None},
                    status=500
                )
            except ValueError as e:
                error_traceback = traceback.format_exc()
                print(f'Error validating story data:')
                print(f'Error: {str(e)}')
                print('Traceback:')
                print(error_traceback)
                return JsonResponse(
                    {"error": str(e),
                     "traceback": error_traceback if settings.DEBUG else None},
                    status=500
                )

        except Exception as e:
            error_traceback = traceback.format_exc()
            print(f'Error generating story:')
            print(f'Error: {str(e)}')
            print('Traceback:')
            print(error_traceback)
            return Response(
                {'error': f'Failed to generate story: {str(e)}',
                 'traceback': error_traceback if settings.DEBUG else None}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class ForgotPasswordView(APIView):
    """
    API endpoint for initiating password reset.
    
    POST /auth/forgot-password/ - Send password reset email
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        """Send password reset email."""
        email = request.data.get('email')
        if not email:
            return Response(
                {'error': 'Email is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            user = User.objects.get(email=email)
            
            # Generate a unique token
            token = get_random_string(length=32)
            expiry = timezone.now() + timedelta(minutes=30)
            
            # Convert expiry to seconds for Redis
            expiry_seconds = int((expiry - timezone.now()).total_seconds())
            
            # Store the token in Redis with expiry
            redis_client.setex(
                f'password_reset:{token}',
                expiry_seconds,  # Use seconds instead of datetime
                json.dumps({
                    'user_id': user.id,
                    'email': user.email
                })
            )
            
            # Generate reset URL
            reset_url = f"{settings.FRONTEND_URL}/reset-password?token={token}"
            resend.api_key = "re_eaD3wimY_NhznCBPAjkVQJ19tDSrewMTv"

            # HTML email template
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Reset Your Password</title>
                <style>
                    body {{
                        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                        line-height: 1.6;
                        color: #333;
                        margin: 0;
                        padding: 0;
                    }}
                    .container {{
                        max-width: 600px;
                        margin: 0 auto;
                        padding: 20px;
                    }}
                    .header {{
                        text-align: center;
                        padding: 20px 0;
                        background: linear-gradient(to right, #4f46e5, #7c3aed);
                        border-radius: 8px 8px 0 0;
                    }}
                    .header h1 {{
                        color: white;
                        margin: 0;
                        font-size: 24px;
                    }}
                    .content {{
                        background: #ffffff;
                        padding: 30px;
                        border-radius: 0 0 8px 8px;
                        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
                    }}
                    .button {{
                        display: inline-block;
                        padding: 12px 24px;
                        background: linear-gradient(to right, #4f46e5, #7c3aed);
                        color: white;
                        text-decoration: none;
                        border-radius: 6px;
                        font-weight: 600;
                        margin: 20px 0;
                    }}
                    .footer {{
                        text-align: center;
                        margin-top: 20px;
                        color: #666;
                        font-size: 14px;
                    }}
                    .warning {{
                        background: #fff3cd;
                        border: 1px solid #ffeeba;
                        color: #856404;
                        padding: 12px;
                        border-radius: 4px;
                        margin: 20px 0;
                    }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>Reset Your Password</h1>
                    </div>
                    <div class="content">
                        <p>Hello,</p>
                        <p>We received a request to reset your password for your WhisprTales account. Click the button below to reset your password:</p>
                        
                        <div style="text-align: center;">
                            <a href="{reset_url}" class="button">Reset Password</a>
                        </div>
                        
                        <p>If the button doesn't work, you can also copy and paste this link into your browser:</p>
                        <p style="word-break: break-all; color: #4f46e5;">{reset_url}</p>
                        
                        <div class="warning">
                            <strong>Note:</strong> This link will expire in 30 minutes for security reasons.
                        </div>
                        
                        <p>If you didn't request a password reset, you can safely ignore this email. Your password will remain unchanged.</p>
                        
                        <p>Best regards,<br>The WhisprTales Team</p>
                    </div>
                    <div class="footer">
                        <p>This is an automated message, please do not reply to this email.</p>
                        <p>&copy; {timezone.now().year} WhisprTales. All rights reserved.</p>
                    </div>
                </div>
            </body>
            </html>
            """

            # Send email using Resend
            r = resend.Emails.send({
                "from": "WhisprTales <support@whisprtales.com>",
                "to": email,
                "subject": "Reset Your WhisprTales Password",
                "html": html_content
            })
            
            print('email sent for forgot password', r)
            return Response({
                'message': 'Password reset email sent successfully'
            })
            
        except User.DoesNotExist:
            # Log the non-existent user attempt
            print(f'Password reset attempt for non-existent user: {email}')
            return Response(
                {'message': 'If an account exists with this email, you will receive a password reset link'},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            # Properly log the exception with traceback
            error_traceback = traceback.format_exc()
            print(f'Exception in forgot password API for email {email}:')
            print(f'Error: {str(e)}')
            print('Traceback:')
            print(error_traceback)
            return Response(
                {'error': 'An unexpected error occurred. Please try again later.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class ResetPasswordView(APIView):
    """
    API endpoint for resetting password.
    
    POST /auth/reset-password/ - Reset password using token
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        """Reset password using token."""
        token = request.data.get('token')
        new_password = request.data.get('password')
        
        if not token or not new_password:
            return Response(
                {'error': 'Token and new password are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get token data from Redis
        token_data = redis_client.get(f'password_reset:{token}')
        if not token_data:
            return Response(
                {'error': 'Invalid or expired token'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            token_data = json.loads(token_data)
            user = User.objects.get(id=token_data['user_id'])
            
            # Update password
            user.set_password(new_password)
            user.save()
            
            # Delete the used token
            redis_client.delete(f'password_reset:{token}')
            
            return Response({
                'message': 'Password reset successful'
            })
            
        except User.DoesNotExist:
            return Response(
                {'error': 'User not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ValidateReferralView(APIView):
    """
    API endpoint for validating referral codes.
    
    POST /auth/validate-referral/ - Validate a referral code
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        """Validate referral code."""
        referral_code = request.data.get('referral_code')

        if not referral_code:
            return Response(
                {'error': 'Referral code is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            if request.user.referred_by:
                return Response(
                    {'error': 'You have alreay applied referral code.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            # Check if referral code exists in User model
            referring_user = User.objects.filter(referral_code=referral_code).first()

            if not referring_user:
                return Response(
                    {'error': 'Invalid referral code'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Check if code is not user's own referral code
            if referring_user == request.user:
                return Response(
                    {'error': 'Cannot use your own referral code'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            return Response({
                'message': 'Valid referral code',
                'discountPercentage': DISCOUNT_PERCENTAGE  # 10% discount
            })

        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class JobViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing jobs.
    
    list:
    Return a list of all jobs for the current user.
    
    retrieve:
    Return the details of a specific job.
    
    create:
    Create a new job.
    
    update:
    Update a job's status and details.
    
    destroy:
    Cancel a job.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = JobSerializer

    def get_queryset(self):
        """Return jobs for the current user."""
        return Job.objects.filter(user=self.request.user)

    def get_serializer_class(self):
        """Return appropriate serializer class."""
        if self.action == 'create':
            return JobCreateSerializer
        return JobSerializer

    def perform_create(self, serializer):
        """Create a new job and send to SQS."""
        try:
            # Save job to database first
            job = serializer.save(user=self.request.user)
            
            # Send to SQS using utility function
            job = send_job_to_sqs(job, job.request_data)
            return job

        except Exception as e:
            error_traceback = traceback.format_exc()
            print(f'Error creating job:')
            print(f'Error: {str(e)}')
            print('Traceback:')
            print(error_traceback)
            # The job is already marked as failed in send_job_to_sqs
            raise

    @action(detail=True, methods=['post'])
    def retry(self, request, pk=None):
        """Retry a failed job."""
        try:
            job = self.get_object()
            
            if job.status != 'failed':
                return Response(
                    {'error': 'Only failed jobs can be retried'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if job.schedule_retry():
                try:
                    # Re-send to SQS using utility function
                    job = send_job_to_sqs(job, job.request_data)
                    return Response({'message': 'Job scheduled for retry'})
                except Exception as e:
                    error_traceback = traceback.format_exc()
                    print(f'Error retrying job {job.job_id}:')
                    print(f'Error: {str(e)}')
                    print('Traceback:')
                    print(error_traceback)
                    # The job is already marked as failed in send_job_to_sqs
                    return Response(
                        {
                            'error': f'Failed to retry job: {str(e)}',
                            'traceback': error_traceback if settings.DEBUG else None
                        },
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )
            else:
                return Response(
                    {'error': 'Maximum retry attempts reached'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except Exception as e:
            error_traceback = traceback.format_exc()
            print(f'Error in job retry endpoint:')
            print(f'Error: {str(e)}')
            print('Traceback:')
            print(error_traceback)
            return Response(
                {
                    'error': str(e),
                    'traceback': error_traceback if settings.DEBUG else None
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Cancel a pending or processing job."""
        job = self.get_object()
        
        if job.status not in ['pending', 'processing']:
            return Response(
                {'error': 'Only pending or processing jobs can be cancelled'},
                status=status.HTTP_400_BAD_REQUEST
            )

        job.cancel()
        return Response({'message': 'Job cancelled successfully'})

