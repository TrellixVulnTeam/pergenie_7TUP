## Getting started

1\. Install requirements

- [Python]() >=2.7,<3
- [PostgreSQL]()
- [MongoDB]()
- [RabbitMQ]()
- Python packages:

```
$ pip install -r requirements/development.txt
```

2\. Configure environments settings

```
$ cp pergenie/pergenie/settings/common.py.example pergenie/pergenie/settings/common.py
$ cp pergenie/pergenie/settings/develop.py.example pergenie/pergenie/settings/develop.py
```

3\. Preparing backends

- Run postgres
- Run mongod
- Run rabbitmq-server

```
$ cd pergenie
$ python manage.py migrate
```

```
$ celery multi start 1 --app=pergenie --loglevel=info --logfile=/tmp/celeryd.log --pidfile=celery%n.pid
$ celery multi restart 1 --logfile=/tmp/celeryd.log --pidfile=celery%n.pid
```

4\. Run

Run local server (for development only)

```
$ python manage.py runserver
```

Browse development server at `http://127.0.0.1:8000/`


## Notes

- Themes
  - [Bootstrap](//getbootstrap.com/), Apache License v2.0
  - Background pattern is downloaded from [subtlepatterns.com](//subtlepatterns.com/), [free to use](//subtlepatterns.com/about/)

- Data visualization
  - Highcharts JS, [for free under the Creative Commons Attribution-NonCommercial 3.0 License](//shop.highsoft.com/highcharts.html)
