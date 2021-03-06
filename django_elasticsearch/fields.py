import django
from django.conf import settings
from django.db import models
from django.core import exceptions, serializers
from django.db.models import Field, CharField
from django.db.models.fields import FieldDoesNotExist
from django.utils.translation import ugettext_lazy as _
from django.db.models.fields import AutoField as DJAutoField
from django.db.models import signals
import uuid

__all__ = ["EmbeddedModel"]
__doc__ = "ElasticSearch special fields"

class EmbeddedModel(models.Model):
    _embedded_in =None

    def save(self, *args, **kwargs):
        if self.pk is None:
            self.pk = str(uuid.uuid4())
        if self._embedded_in  is None:
            raise RuntimeError("Invalid save")
        self._embedded_in.save()

    def serialize(self):
        if self.pk is None:
            self.pk = unicode(ObjectId())
            self.id = self.pk
        result = {'_app':self._meta.app_label,
            '_model':self._meta.module_name,
            '_id':self.pk}
        for field in self._meta.fields:
            result[field.attname] = getattr(self, field.attname)
        return result
    
class ElasticField(CharField):
    
    def __init__(self, *args, **kwargs):
        self.doc_type = kwargs.pop("doc_type", None)
        
        # This field stores the document id and has to be unique
        kwargs["unique"] = True
        
        # Let's force the field as db_index so we can get its value faster.
        kwargs["db_index"] = True
        kwargs["max_length"] = 255
        
        super(ElasticField, self).__init__(*args, **kwargs)

    def contribute_to_class(self, cls, name):
        super(ElasticField, self).contribute_to_class(cls, name)
        
        
        index = cls._meta.db_table
        doc_type = self.doc_type
        att_id_name = "_%s_id" % name
        att_cache_name = "_%s_cache" % name
        att_val_name = "_%s_val" % name
        
        def _get(self):
            """
            self is the model instance not the field instance
            """
            from django.db import connections
            elst = connections[self._meta.elst_connection]
            if not hasattr(self, att_cache_name) and not getattr(self, att_val_name, None) and getattr(self, att_id_name, None):
#                elst = ElasticSearch('http://127.0.0.1:9200/')
                val = elst.get(index, doc_type, id=getattr(self, att_id_name)).get("_source", None)
                setattr(self, att_cache_name, val)
                setattr(self, att_val_name, val)
            return getattr(self, att_val_name, None)

        def _set(self, val):
            """
            self is the model instance not the field instance
            """
            if isinstance(val, basestring) and not hasattr(self, att_id_name):
                setattr(self, att_id_name, val)
            else:
                setattr(self, att_val_name, val or None)

        setattr(cls, self.attname, property(_get, _set))

    
#    def db_type(self, connection):
#        return "elst"

    def pre_save(self, model_instance, add):
        from django.db import connections
        elst = connections[model_instance._meta.elst_connection]
        
        id = getattr(model_instance, "_%s_id" % self.attname, None)
        value = getattr(model_instance, "_%s_val" % self.attname, None)
        index = model_instance._meta.db_table
        doc_type = self.doc_type

        if value == getattr(model_instance, "_%s_cache" % self.attname, None) and id:
            return id
        
        if value:
#            elst = ElasticSearch('http://127.0.0.1:9200/')
            result = elst.index(doc=value, index=index, doc_type=doc_type, id=id or None)
            setattr(model_instance, "_%s_id" % self.attname, result["_id"])
            setattr(model_instance, "_%s_cache" % self.attname, value)
        return getattr(model_instance, "_%s_id" % self.attname, u"")
    
#
# Fix standard models to work with elasticsearch
#

def autofield_to_python(value):
    if value is None:
        return value
    try:
        return str(value)
    except (TypeError, ValueError):
        raise exceptions.ValidationError(self.error_messages['invalid'])

def autofield_get_prep_value(value):
    if value is None:
        return None
    return unicode(value)

def add_elasticsearch_manager(sender, **kwargs):
    """
    Fix autofield
    """
    cls = sender
    database = settings.DATABASES[cls.objects.db]
    if 'django_elasticsearch' in database['ENGINE']:
#        print getattr(django, 'MODIFIED', "NOOO")
        if not hasattr(django, 'MODIFIED') and isinstance(cls._meta.pk, DJAutoField):
            pk = cls._meta.pk
            setattr(pk, "to_python", autofield_to_python)
            setattr(pk, "get_prep_value", autofield_get_prep_value)
            cls = sender
        if cls._meta.abstract:
            return
