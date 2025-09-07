from django.db import models

# Create your models here.
class Category(models.Model):
    name = models.CharField(max_length=50)
    slug = models.CharField(max_length=50, unique = True)
    description = models.CharField(max_length=250, blank = True)
    image = models.ImageField(upload_to= 'photos/categories', blank = True)

    class Meta:
        verbose_name = 'category'
        verbose_name_plural = 'categories'
    def __str__(self):
        return self.name
    
