# Copyright 2011 Josh Bronson <jabronson@gmail.com>

from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash
from functools import wraps
#from geo.geomodel import GeoModel
from google.appengine.ext import db
from itertools import count
from random import random
from werkzeug import url_decode
from werkzeug.exceptions import BadRequest, NotFound
import settings

class MethodRewriteMiddleware(object):
    '''
    Middleware for HTTP method rewriting.
    Snippet: http://flask.pocoo.org/snippets/38/
    '''
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        if 'METHOD_OVERRIDE' in environ.get('QUERY_STRING', ''):
            args = url_decode(environ['QUERY_STRING'])
            method = args.get('__METHOD_OVERRIDE__')
            if method:
                method = method.encode('ascii', 'replace')
                environ['REQUEST_METHOD'] = method
        return self.app(environ, start_response)

app = Flask(__name__)
app.config['SECRET_KEY'] = settings.secret_key
app.wsgi_app = MethodRewriteMiddleware(app.wsgi_app)

class InvalidId(Exception): pass
class InvalidInput(Exception): pass

class Checkin(object):
    def __init__(self, lat, lon, val):
        self._id = None
        self.lat = lat
        self.lon = lon
        self.val = val
        self.time_c = self.time_m = self.time_a = datetime.utcnow()

    @property
    def id(self):
        return self._id

    def update(self, lat, lon, val):
        self.lat = lat
        self.lon = lon
        self.val = val
        self.time_m = self.time_a = datetime.utcnow()

    def __repr__(self):
        return '<%s id=%r lat=%r lon=%r val=%r>' % (self.__class__.__name__,
            self.id, self.lat, self.lon, self.val)

class GAECheckin(db.Model, Checkin):
    lat = db.FloatProperty()
    lon = db.FloatProperty()
    val = db.FloatProperty()
    time_c = db.DateTimeProperty()
    time_m = db.DateTimeProperty()
    time_a = db.DateTimeProperty()

    def __init__(self, *args, **kw):
        db.Model.__init__(self, *args, **kw)
        self.time_c = self.time_m = self.time_a = datetime.utcnow()

    @property
    def id(self):
        return self.key().id()

class CheckinStore(object):
    '''
    Abstract base class for Checkin stores.
    '''
    def get(self, id):
        raise NotImplementedError
    def add(self, lat, lon, val):
        raise NotImplementedError
    def remove(self, id):
        raise NotImplementedError
    def update(self, lat, lon, val):
        raise NotImplementedError
    def __iter__(self):
        raise NotImplementedError

class TmpCheckinStore(CheckinStore):
    '''
    CheckinStore which stores data in memory.
    All data lost when process terminates.
    '''
    def __init__(self):
        self.checkins = {}
        self.counter = count()

    def get(self, id):
        try:
            checkin = self.checkins[id]
        except:
            raise InvalidId(id)
        checkin.time_a = datetime.utcnow()
        return checkin

    def add(self, lat, lon, val):
        id = self.counter.next()
        checkin = Checkin(lat, lon, val)
        self.checkins[id] = checkin
        checkin._id = id
        return checkin

    def remove(self, id):
        try:
            del self.checkins[id]
        except:
            raise InvalidId(id)

    def update(self, id, lat, lon, val):
        try:
            checkin = self.checkins[id]
        except:
            raise InvalidId(id)
        checkin.update(lat, lon, val)

    def __iter__(self):
        return self.checkins.itervalues()

class GAECheckinStore(CheckinStore):
    '''
    CheckinStore which stores data in App Engine's data store.
    '''
    def get(self, id):
        try:
            key = db.Key.from_path('GAECheckin', id)
            checkin = db.get(key)
            assert checkin is not None
        except: # XXX
            raise InvalidId
        checkin.time_a = datetime.utcnow()
        return checkin

    def add(self, lat, lon, val):
        checkin = GAECheckin(lat=lat, lon=lon, val=val)
        id = db.put(checkin).id()
        return db.get(db.Key.from_path('GAECheckin', id))

    def remove(self, id):
        try:
            key = db.Key.from_path('GAECheckin', id)
            db.delete(key)
        except: # XXX
            raise InvalidId

    def update(self, id, lat, lon, val):
        try:
            key = db.Key.from_path('GAECheckin', id)
            checkin = db.get(key)
            assert checkin is not None
        except: # XXX
            raise InvalidId
        checkin.update(lat, lon, val)
        checkin.put()

    def __iter__(self):
        return iter(GAECheckin.all())

def scale(x, bounds):
    '''
    Takes some x presumed to be in [0, 1) and scales it into the interval
    [bounds[0], bounds[1]).

    >>> scale(0.5, (5, 10))
    7.5
    '''
    length = bounds[1] - bounds[0]
    return x*length + bounds[0]

def add_random_checkins(checkinstore, n=10, latbounds=(35, 40),
    lonbounds=(-80, -75), valbounds=(0, 100)):
    for i in xrange(n):
        lat = scale(random(), latbounds)
        lon = scale(random(), lonbounds)
        val = scale(random(), valbounds)
        checkinstore.add(lat, lon, val)

@app.route('/checkins/new')
def checkins_new_form():
    '''
    GET /checkins/new

    Renders form for new checkin.
    '''
    return render_template('checkins/new.html', settings=settings)

def _checkin_data_from_req():
    try:
        return [float(request.form[i]) for i in ('lat', 'lon', 'val')]
    except:
        raise InvalidInput

_400_invalid_input = BadRequest('Invalid input')
@app.route('/checkins/new', methods=['POST'])
def checkins_new():
    '''
    POST /checkins/new

    Creates new checkin from request data.
    '''
    try:
        lat, lon, val = _checkin_data_from_req()
    except InvalidInput:
        raise _400_invalid_input
    checkin = checkinstore.add(lat, lon, val)
    flash('checkin saved')
    return redirect(url_for('checkins_edit_form', id=checkin.id))

_404_invalid_id = NotFound('Invalid id')
@app.route('/checkins/<id>')
def checkins_edit_form(id):
    '''
    GET /checkins/<id>
    '''
    try:
        id = int(id)
        checkin = checkinstore.get(id)
    except (ValueError, InvalidId):
        raise _404_invalid_id
    return render_template('checkins/edit.html', checkin=checkin,
        settings=settings)

@app.route('/checkins/<id>', methods=['PUT'])
def checkins_edit(id):
    '''
    PUT /checkins/<id>

    Updates specified checkin from request data.
    '''
    try:
        lat, lon, val = _checkin_data_from_req()
    except InvalidInput:
        raise _400_invalid_input
    try:
        id = int(id)
        checkinstore.update(id, lat, lon, val)
    except (ValueError, InvalidId):
        raise _404_invalid_id
    flash('checkin updated')
    return redirect(url_for('checkins_edit_form', id=id))

@app.route('/checkins/<id>', methods=['DELETE'])
def checkins_delete(id):
    '''
    DELETE /checkins/<id>
    '''
    try:
        id = int(id)
        checkinstore.remove(id)
    except (ValueError, InvalidId):
        raise _404_invalid_id
    flash('checkin deleted')
    return redirect(url_for('checkins_view_all'))

@app.route('/checkins')
def checkins_view_all():
    '''
    GET /checkins

    View all checkins
    '''
    list(checkinstore)
    return render_template('checkins/view_all.html',
        checkins=checkinstore, settings=settings)

@app.route('/')
def root():
    return redirect(url_for('checkins_view_all'))

try:
    from google.appengine.ext.webapp.util import run_wsgi_app
    app.config['DEBUG'] = settings.debug = False
    checkinstore = GAECheckinStore()
    run_wsgi_app(app)
except ImportError:
    app.config['DEBUG'] = settings.debug
    checkinstore = TmpCheckinStore()
    add_random_checkins(checkinstore)
    app.run()
