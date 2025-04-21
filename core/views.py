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
# from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
# from allauth.socialaccount.providers.oauth2.client import OAuth2Client
# from dj_rest_auth.registration.views import SocialLoginView
from .models import Story, Scene, Media
from .serializers import (
    UserSerializer, UserRegistrationSerializer,
    StorySerializer, StoryCreateSerializer,
    SceneSerializer, MediaSerializer
)
from django.contrib.auth import get_user_model
import json
from openai import OpenAI
from django.conf import settings
import openai
import os
from rest_framework import viewsets
from rest_framework.decorators import action
import boto3
from io import BytesIO
import requests
from datetime import datetime

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
        """Generate images for all scenes in the story."""
        story = self.get_object(pk)
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
                # response = client.images.generate(
                #     model="dall-e-3",
                #     prompt=f"Generate a detailed, high-quality image for this scene: {scene.content}",
                #     size="1024x1024",
                #     quality="standard",
                #     n=1,
                #     response_format="url"
                # )
                
                # # Get the image URL from OpenAI
                # image_url = response.data[0].url
                
                # # Download the image
                # image_response = requests.get(image_url)
                # image_data = BytesIO(image_response.content)
                
                # # Generate a unique filename
                # timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                # filename = f"story_{story.id}/scene_{scene.id}/image_{timestamp}.png"
                
                # # Upload to S3
                # s3_client.upload_fileobj(
                #     image_data,
                #     settings.IMAGE_AWS_STORAGE_BUCKET_NAME,
                #     filename,
                #     ExtraArgs={'ACL': 'public-read'}
                # )
                
                # # Create S3 URL
                # s3_url = f"https://{settings.IMAGE_AWS_S3_CUSTOM_DOMAIN}/{filename}"
                s3_url = 'https://story-generation-image.s3.amazonaws.com/story_5/scene_56/image_20250418_150012.png'
                # Create a new Media instance for the generated image
                Media.objects.create(
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
            from openai import OpenAI
            from django.conf import settings
            
            # Initialize OpenAI client
            print(settings.CHATGPT_OPENAI_API_KEY)
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
            
            Story: {story.content}
            
            Format the response as JSON with the following structure:
            {{
                "scenes": [
                    {{
                        "title": "Scene title",
                        "content": "Scene content",
                        "scene_description": "Brief description",
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
                    order=scene_data['order']
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
        """Generate an image for the scene."""
        scene = self.get_object(story_pk, pk)
        
        try:
            # Initialize S3 client
            # s3_client = boto3.client(
            #     's3',
            #     aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            #     aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            #     region_name=settings.AWS_S3_REGION_NAME
            # )
            
            # # Initialize OpenAI client
            # client = OpenAI(api_key=settings.CHATGPT_OPENAI_API_KEY)
            
            # # Generate image using OpenAI's DALL-E
            # response = client.images.generate(
            #     model="dall-e-3",
            #     prompt=f"Generate a detailed, high-quality image for this scene: {scene.content}",
            #     size="1024x1024",
            #     quality="standard",
            #     n=1,
            #     response_format="url"
            # )
            
            # # Get the image URL from OpenAI
            # image_url = response.data[0].url
            
            # # Download the image
            # image_response = requests.get(image_url)
            # image_data = BytesIO(image_response.content)
            
            # # Generate a unique filename
            # timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            # filename = f"story_{scene.story.id}/scene_{scene.id}/image_{timestamp}.png"
            
            # # Upload to S3
            # s3_client.upload_fileobj(
            #     image_data,
            #     settings.IMAGE_AWS_STORAGE_BUCKET_NAME,
            #     filename
            # )
            
            # # Create S3 URL
            # s3_url = f"https://{settings.IMAGE_AWS_S3_CUSTOM_DOMAIN}/{filename}"
            # print(s3_url)
            s3_url = 'https://story-generation-image.s3.amazonaws.com/story_5/scene_56/image_20250418_150012.png'
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
                Media.objects.create(
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
            
            from openai import OpenAI

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

class StoryPreviewPDFView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, story_id):
        try:
            story = Story.objects.get(id=story_id, author=request.user)
            
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
                'action': 'generate_pdf_preview'
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
            print(e)
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
