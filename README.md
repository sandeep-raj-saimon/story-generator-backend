# WhisprTales Backend

A Django REST API backend for the WhisprTales application.

## Setup

1. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create a .env file in the root directory with the following variables:
```
SECRET_KEY=your_django_secret_key
DEBUG=True
DATABASE_URL=postgres://user:password@localhost:5432/story_generator
```

4. Run migrations:
```bash
python manage.py migrate
```

5. Create a superuser:
```bash
python manage.py createsuperuser
```

6. Run the development server:
```bash
python manage.py runserver
```

## API Endpoints

### Authentication
- POST /api/auth/register/ - User registration
- POST /api/auth/login/ - User login
- POST /api/auth/refresh/ - Refresh JWT token

### Stories
- GET /api/stories/ - List all stories
- POST /api/stories/ - Create a new story
- GET /api/stories/{id}/ - Get story details
- PUT /api/stories/{id}/ - Update story
- DELETE /api/stories/{id}/ - Delete story

### Scenes
- GET /api/stories/{story_id}/scenes/ - List scenes for a story
- POST /api/stories/{story_id}/scenes/ - Create a new scene
- GET /api/scenes/{id}/ - Get scene details
- PUT /api/scenes/{id}/ - Update scene
- DELETE /api/scenes/{id}/ - Delete scene


my requirements are:
1. user would be able to create a story
2. user would be able to edit a story
3. user would be able to delete a story
4. now once story has been finalized, we would divide that story into differnet segments and each ssegment would have its own scene description
5. once segments has been finalized and created, user can edit and delete a scene description, user can create a scene(image or audiof) or each segment based on scene description
6. if user is not satisfied with the scene, user can ask to generate that scene again
7. after all story has been finalized, user can ask to generate a story based on the segments and scene descriptions
8. user can generate/download the story in different formats like pdf, mp4
9. mp4 can include videos(by concatenating images), audios and can be generated using different models like stable diffusion, midjourney, etc.