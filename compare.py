""" run the comparisons using asyncio """

import time
import asyncio
import asks
import trio
import settings
import aiohttp
import secrets
from flask_bootstrap import Bootstrap
from collections import OrderedDict
from flask_wtf import FlaskForm
from wtforms import TextAreaField, SubmitField
from wtforms.validators import Length
from flask import Flask, render_template, request, url_for, Response, abort
from datetime import datetime

app = Flask(__name__, static_url_path="/static")
Bootstrap(app)
app.config["SECRET_KEY"] = secrets.token_hex()


class WebForm(FlaskForm):
    """ for validation """

    web_abstract_var = TextAreaField(
        validators=[
            Length(
                min=150,
                max=10000,
                message="Your abstract must be between 150 and 10,000 characters.",
            )
        ]
    )
    submit = SubmitField("Search")


@app.route("/", methods=["GET", "POST"])
def index():
    """ display index page """
    form = WebForm()
    if request.method == "POST" and form.validate_on_submit():
        comp = {}
        unordered_scores = {}
        inp = form.web_abstract_var.data
        t0 = datetime.now()

        # do the work
        asyncio.run(parent(inp, comp))
        trio.run(tabulate, comp, unordered_scores)

        # sort the results
        scores = OrderedDict(
            sorted(unordered_scores.items(), key=lambda t: t[0], reverse=True)
        )

        # calculate running time
        t1 = datetime.now()
        print(t1 - t0)

        return render_template("index.html", form=form, errors={}, output=scores)

    elif request.method == "POST" and not form.validate_on_submit():
        return render_template("index.html", form=form, errors=form.errors, output="")

    else:
        return render_template("index.html", form=form, errors={}, output="")


async def parent(inp, comp):
    """ manage the async work """
    await asyncio.gather(*[storageio(blob, inp, comp) for blob in settings.bucket_list])
    return


async def storageio(blob, inp, comp):
    """ interact with google cloud function """
    status = 0
    max_out = 0
    error = False
    async with aiohttp.ClientSession() as session:
        while ((status != 200) or (error == True)) and (max_out < 15):
            try:
                async with session.post(
                    settings.cloud_function,
                    json={"d": inp, "f": blob, "t": settings.token},
                ) as resp:
                    status = resp.status
                    if status == 403:
                        abort(403)
                    max_out += 1
                    comp[blob[10:19]] = await resp.text()
                    error = False
            except (
                asyncio.TimeoutError,
                aiohttp.client_exceptions.ClientConnectorError,
                aiohttp.client_exceptions.ServerDisconnectedError,
            ):
                error = True
                pass
    return


def test_response(resp):
    """ some abstract collections raise ValueErrors. Ignore these """
    try:
        return float(resp)  # will evaluate as false if float == 0.0
    except ValueError:
        return False


async def tabulate(comp, unordered_scores):

    # test for validity
    to_sort = [(k, v) for k, v in comp.items() if test_response(v)]
    print("Journals checked:" + str(len(to_sort)))

    # this sort is needed to reduce API calls to doaj.org
    top = sorted(to_sort, key=lambda x: x[1], reverse=True)[:5]

    # make calls to the doaj API asynchronously
    async with trio.open_nursery() as nursery:
        for idx, item in enumerate(top):
            nursery.start_soon(titles, idx, item, unordered_scores)
    return


async def titles(idx, item, unordered_scores):
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
    try:
        url = journal_json["results"][0]["bibjson"]["link"][0]["url"]
    except:
        url = ""
    issn = item[0]
    score = float(item[1]) * 100
    unordered_scores[score] = (title, issn, url)
    return


if __name__ == "__main__":
    app.run()
