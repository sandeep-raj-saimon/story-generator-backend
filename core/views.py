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

# from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
# from allauth.socialaccount.providers.oauth2.client import OAuth2Client
# from dj_rest_auth.registration.views import SocialLoginView
from .models import Story, Scene, Media, Revision
from .serializers import (
    UserSerializer, UserRegistrationSerializer,
    StorySerializer, StoryCreateSerializer,
    SceneSerializer, MediaSerializer,
    RevisionSerializer
)
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

# class GoogleLogin(SocialLoginView):
#     """
#     API endpoint for Google SSO login.
    
#     POST /auth/google/ - Login with Google
#     """
#     adapter_class = GoogleOAuth2Adapter
#     callback_url = "http://localhost:3000"  # Your frontend URL
#     client_class = OAuth2Client

#     def post(self, request, *args, **kwargs):
#         """Handle Google SSO login."""
#         response = super().post(request, *args, **kwargs)
        
#         if response.status_code == 200:
#             # Get the user from the response
#             user = request.user
            
#             # Generate JWT tokens
#             refresh = RefreshToken.for_user(user)
            
#             # Add tokens to the response
#             response.data.update({
#                 'refresh': str(refresh),
#                 'access': str(refresh.access_token),
#             })
        
#         return response

# Create your views here.

class StoryListCreateAPIView(APIView):
    """
    API endpoint for listing and creating stories.
    
    GET /stories/ - List all stories for the current user
    POST /stories/ - Create a new story
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        """List all stories for the current user."""
        stories = Story.objects.filter(author=request.user)
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
        serializer = StorySerializer(story, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

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
            for scene in scenes:
                # Initialize SQS client
                sqs_client = boto3.client(
                    'sqs',
                    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                    region_name=settings.AWS_S3_REGION_NAME
                )
                
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
            2. The scene content
            3. A brief description
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
        scenes = Scene.objects.filter(story_id=story_pk, story__author=request.user)
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
        # Get the URL pattern name to determine which endpoint was called
        url_name = request.resolver_match.url_name
        
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
                    message['voice_id'] = voice_id
                except Exception as e:
                    return Response(
                        {'error': f'Error processing request data: {str(e)}'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            # Send message to SQS queue
            response = sqs_client.send_message(
                QueueUrl=settings.STORY_GENERATION_QUEUE_URL,
                MessageBody=json.dumps(message)
            )
            
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

class UserRegistrationAPIView(APIView):
    """
    API endpoint for user registration.
    
    POST /auth/register/ - Register a new user
    """
    permission_classes = [permissions.AllowAny]
    @method_decorator(csrf_exempt)
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

class UserLoginAPIView(APIView):
    """
    API endpoint for user login.
    
    POST /auth/login/ - Login a user
    """
    permission_classes = [permissions.AllowAny]
    @method_decorator(csrf_exempt)
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
