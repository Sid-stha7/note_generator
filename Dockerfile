# Use a suitable Python image as the base
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set the working directory inside the container
WORKDIR /usr/src/app

# Copy requirements file and install dependencies
COPY requirements.txt /usr/src/app/

# Install the dependencies listed in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire project code into the container
COPY . /usr/src/app/

# Expose the port where Django will listen
EXPOSE 8000

# The command to run the Django development server
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]