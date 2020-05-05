import requests
import time
import asks
import trio
import settings
import secrets
import json
try:
    import googleclouddebugger
    googleclouddebugger.enable()
except ImportError:
    pass
from google.cloud import pubsub_v1
from flask_bootstrap import Bootstrap
from flask_wtf import FlaskForm
from wtforms import TextAreaField, SubmitField
from wtforms.validators import Length
from flask import Flask, render_template, request, url_for, Response
from datetime import datetime

print("libraries loaded...")

app = Flask(__name__, static_url_path="/static")
Bootstrap(app)
app.config["SECRET_KEY"] = secrets.token_hex()

publisher = pubsub_v1.PublisherClient()
topic_path = publisher.topic_path(settings.project_id, settings.topic_name)


class WebForm(FlaskForm):
    """ for validation """

    web_abstract_var = TextAreaField(
        validators=[
            Length(
                min=25,
                max=10000,
                message="Your abstract must be between 25 and 10000 characters.",
            )
        ],
    )
    submit = SubmitField("Search")


@app.route("/", methods=["GET", "POST"])
def index():
    """ display index page """
    print("index function called...")
    form = WebForm()
    if request.method == "POST" and form.validate_on_submit():
        futures = dict()
        inp = form.web_abstract_var.data
        print(inp)
        t0 = datetime.now()

        # do the work
        for blob in settings.bucket_list:
            data = json.dumps({"d": inp, "f": blob})
            futures.update({data: None})
            future = publisher.publish(topic_path, data=data.encode('utf-8'))
            print(future.result())
            futures[data] = future
            future.add_done_callback(get_callback(future, data))

        while futures:
            time.sleep(5)

        print("did pubsub")

        scores = sorted(result, key=lambda t: t[1], reverse=True)

        output = {}
        trio.run(tabulate, scores[:5], output)
        output_list = [v for v in output.values()]
        sorted_output = sorted(output_list, key=lambda t: t[0], reverse=True)

        # calculate running time
        t1 = datetime.now()
        print(t1 - t0)

        return render_template("index.html", form=form, errors={}, output=sorted_output)

    elif request.method == "POST" and not form.validate_on_submit():
        return render_template("index.html", form=form, errors=form.errors, output="")

    else:
        print("at render...")
        return render_template("index.html", form=form, errors={}, output="")

def get_callback(f, data):
    def callback(f):
        try:
            #print(f.result())
            futures.pop(data)
        except:  # noqa
            #print("Please handle {} for {}.".format(f.exception(), data))
            pass
    return callback

"""
@task(name="access_storage")
def storageio(blob, inp):

    return (blob[10:19], resp.text)
"""

def test_response(resp):
    """ some abstract collections raise ValueErrors. Ignore these. """
    try:
        return float(resp)  # will evaluate as false if float == 0.0
    except ValueError:
        return False


async def tabulate(scores, output):

    # test for validity
    tested = [[item[0], item[1]] for item in scores if test_response(item[1])]
    print("Journals checked:" + str(len(tested)))

    # make calls to the doaj API asynchronously
    async with trio.open_nursery() as nursery:
        for item in tested:
            nursery.start_soon(titles, item, output)
    return


async def titles(item, output):
    journal_data = await asks.get(
        "https://doaj.org/api/v1/search/journals/issn%3A" + item[0]
    )
    journal_json = journal_data.json()
    try:
        title = journal_json["results"][0]["bibjson"]["title"]
        if title[-1:] == " ":
            title = title[:-1]
    except:
        title = "Title lookup failed. Try finding this item by ISSN instead.."
    issn = item[0]
    score = float(item[1]) * 100
    output[issn] = [score, title, issn]
    return


if __name__ == "__main__":
    app.run(port=8000, host="127.0.0.1", debug=True)
