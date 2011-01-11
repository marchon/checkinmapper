# Copyright 2011 Josh Bronson <jabronson@gmail.com>

from flask import Flask, render_template, request, redirect, url_for, flash
from functools import wraps
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

class Checkin(object):
    def __init__(self, lat, lon, val):
        self.id = None
        self.lat = lat
        self.lon = lon
        self.val = val

    def update(self, lat, lon, val):
        self.lat = lat
        self.lon = lon
        self.val = val

    def __repr__(self):
        return '<%s lat=%r lon=%r val=%r>' % (self.__class__.__name__,
            self.lat, self.lon, self.val)

class InvalidId(Exception): pass
class CheckinStore(object):
    def get(self, id):
        raise NotImplementedError
    def add(self, checkin):
        raise NotImplementedError
    def remove(self, id):
        raise NotImplementedError
    def update(self, checkin):
        raise NotImplementedError
    def __iter__(self):
        raise NotImplementedError

class InMemoryCheckinStore(CheckinStore):
    def __init__(self):
        self.checkins = {}
        self.counter = count()

    def get(self, id):
        try:
            return self.checkins[int(id)]
        except:
            raise InvalidId(id)

    def add(self, checkin):
        id = self.counter.next()
        checkin.id = id
        self.checkins[id] = checkin

    def remove(self, id):
        try:
            del self.checkins[int(id)]
        except:
            raise InvalidId(id)

    def update(self, checkin):
        pass # no need to do anything since checkin stored in memory

    def __iter__(self):
        return self.checkins.itervalues()

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
        checkin = Checkin(lat, lon, val)
        checkinstore.add(checkin)

checkinstore = InMemoryCheckinStore()
add_random_checkins(checkinstore)

def errortransform(errormap):
    def inner(func):
        @wraps(func)
        def wrapper(*args, **kw):
            try:
                return func(*args, **kw)
            except Exception, e:
                eclass = e.__class__
                if eclass in errormap:
                    raiseinstead = errormap[e.__class__]
                    if raiseinstead is None:
                        return
                    raise raiseinstead
                raise
        return wrapper
    return inner

app = Flask(__name__)
app.config['SECRET_KEY'] = settings.secret_key
app.wsgi_app = MethodRewriteMiddleware(app.wsgi_app)

@app.route('/checkins/new')
def checkins_new_form():
    '''
    GET /checkins/new

    Renders form for new checkin.
    '''
    return render_template('checkins/new.html', settings=settings)

class InvalidInput(Exception): pass
def _checkin_data_from_req():
    try:
        return [float(request.form[i]) for i in ('lat', 'lon', 'val')]
    except:
        raise InvalidInput

@app.route('/checkins/new', methods=['POST'])
@errortransform({InvalidId: NotFound, InvalidInput: BadRequest})
def checkins_new():
    '''
    POST /checkins/new

    Creates new checkin from request data.
    '''
    lat, lon, val = _checkin_data_from_req()
    checkin = Checkin(lat, lon, val)
    checkinstore.add(checkin)
    flash('checkin saved')
    return redirect(url_for('checkins_edit_form', id=checkin.id))

@app.route('/checkins/<id>')
@errortransform({InvalidId: NotFound})
def checkins_edit_form(id):
    '''
    GET /checkins/<id>
    '''
    checkin = checkinstore.get(id)
    return render_template('checkins/edit.html', checkin=checkin,
        settings=settings)

@app.route('/checkins/<id>', methods=['PUT'])
@errortransform({InvalidId: NotFound, InvalidInput: BadRequest})
def checkins_edit(id):
    '''
    PUT /checkins/<id>

    Updates specified checkin from request data.
    '''
    checkin = checkinstore.get(id)
    lat, lon, val = _checkin_data_from_req()
    checkin.update(lat, lon, val)
    flash('checkin updated')
    return redirect(url_for('checkins_edit_form', id=checkin.id))

@app.route('/checkins/<id>', methods=['DELETE'])
@errortransform({InvalidId: NotFound})
def checkins_delete(id):
    '''
    DELETE /checkins/<id>
    '''
    checkinstore.remove(id)
    flash('checkin deleted')
    return redirect(url_for('checkins_view_all'))

@app.route('/checkins')
def checkins_view_all():
    '''
    GET /checkins

    View all checkins
    '''
    return render_template('checkins/view_all.html',
        checkins=checkinstore, settings=settings)

@app.route('/')
def root():
    return redirect(url_for('checkins_view_all'))

try:
    from google.appengine.ext.webapp.util import run_wsgi_app
    run_wsgi_app(app)
except ImportError:
    app.config['DEBUG'] = settings.debug
    app.run()
