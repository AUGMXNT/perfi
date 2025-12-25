# How the GUI works and how the app gets packaged

# The GUI

The GUI is a single page JS app written in Typescript. We use Vue.js for routing/rendering components, Pinia for some state management of record collections, Quasar for the UI components, and Vite for the build system. The GUI reads and writes data by talking to an API server running on the same host.

**Frontend**

The Frontend app is built with Vue.js. Vue is similar to React; it allows you to compose pages comprised of components which selectively re-render to update the UI when a component’s backing data changes. The frontend files live in `frontend/`.

One common pattern in data-driven apps is to have *stores* which are responsible for loading data from an API server, keeping that data up-to-date in-memory, and providing the data for components to use when they are rendered. Vue recommends Pinia for data store management, so we use that. Our stores are very straightforward and all follow a similar pattern where they have an async method to load an initial collection of data from the API server into memory, and they have events to update that data in-memory in response to triggered events from the rendered components. See `frontend/stores/entities.ts` for an example.

We use [Quasar](https://quasar.dev) for its grid layout framework and for many of its pre-built components to help deliver a UI with a consistent look and feel. Quasar has large collection of Vue components, each with extensive documentation. See [https://quasar.dev/vue-components](https://quasar.dev/vue-components) for more info.

**Backend**

The backend API server is written in Python and uses FastAPI. The API file lives in `perfi/api.py` If you know how FastAPI works, you’ll understand most of how the file is written. There are just a few notable things that might be unusual.

*CORS:* We need to set proper CORS headers on API responses so that browsers are OK to talk to the API. Since CORS origin values require a host and a port, and since the API server port (and the Web asset server port) may be dynamic (set via ENV vars), we have a set of hardcoded default origins which we extend with values that are present in the ENV vars. Look for `API_PORT` and `FRONTEND_PORT` env var usage in the file for more info.

*EnsureRecord pattern:* Many API endpoints require an entity ID (for example `/entities/1` or `/entities/1/addresses` or `addresses/1` etc). FastAPI has a dependency injection system to provide values to your routes, and we leverage this here with an `EnsureRecord` class which gives us an easy way to query a particular data store (e.g. `EntitiesStore` or `AddressesStore` etc) for a given entity. For example: 

```python
@app.get("/entities/{id}")
def list_addresses_for_entity(entity: Entity = Depends(EnsureRecord("entity"))):
    return entity
```

Here, you can see we define a GET to `/entities/{id}` and we load that entity via querying the entity store for a record with that ID via the `EnsureRecord` dependency.

*Running CLI bins:* Some of the API endpoints delete their work to simply executing one of the existing CLI bin commands. This is just so we don’t have to duplicate logic that’s already defined in the command handlers for the CLI. 

```python
from bin.cli import (
    ledger_update_logical_type,
    ledger_update_ledger_type,
    ledger_update_price,
    ledger_flag_logical,
    ledger_remove_flag_logical,
    ledger_move_tx_ledger,
)
```

# Packaging the app

**Electron**

We use Electron to bootstrap the app (start the API and Web asset servers, then open a chrome-less browser window to show the Single-Page App GUI. The electron files live in `electron/`.

In order to start the API and Web Asset servers, we need to find free ports on the host system and start python processes for the servers, passing those ports in appropriately (via ENV vars). This happens inside the electron app’s entry point file `electron/src/index.js` — see `createWindow()` for the details.

 

Packaging the electron app is accomplished using a tool called `electron-builder` which simply looks at some configuration data describing which OS/package formats to build for and then builds them. However since all Electron knows how to do is run Node.js code and open a web view, we need a way to take our API server and package it up with all of its python dependencies so it can run on the target host. For this, we use PyInstaller.

**PyInstaller**

From PyInstaller’s website: “PyInstaller bundles a Python application and all its dependencies into a single package. The user can run the packaged app without installing a Python interpreter or any modules. PyInstaller supports Python 3.7 and newer, and correctly bundles many major Python packages such as numpy, matplotlib, PyQt, wxPython, and others.”  After examining a python file for packaging, PyInstaller produces a `.spec` file (which is executable Python code) outlining exactly what it will package, and how. Our entry point for PyInstaller is `app_main.py` and the corresponding spec file is `app_main.spec`

`app_main.py`'s job is simply to spin up the backend API server (for the Frontend JS app to use) and a simple HTTP static file server (to serve the Frontend JS app itself). It takes in `API_PORT` and `FRONTEND_PORT` env vars and defaults to `5000` and `5001` when those envs are not present.

Sometimes, it can be useful to know if Python code is executing inside a PyInstaller packaged python, or from without. This snippet helps here: `IS_PYINSTALLER = getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")` We use this technique inside `perfi/constants/paths.py` in order to set the parent dir in the `DATA_DIR` and `CACHE_DIR` variables. For local development, we proceed as we did before, simply looking for the git root dir. But for the PyInstaller version, we use OS-specific sensible locations. See `get_user_data_dir()` for more info.

An important detail about PyInstaller is that it is not a cross-compiler; it can only successfully package up python for the OS that you run the command inside. So, we use GitHub Actions to build out our final application, since we can run build steps on Windows, Ubuntu, and Mac hosts there.

**GitHub Actions**

Inside `.github/workflows/build_releases.yml` you’ll find the GitHub Actions workflow file that controls how our app is built.  The workflow runs whenever a new tag matching the pattern `v*` is pushed to GitHub (e.g. `v1.0.0' or 'vFoo'). The workflow will build out the app and put the final product into a new GitHub release named after the `version` value inside `electron/package.json` (not the tag name you use). So, make sure you bump that version number in the `electron/package.json` before you push a new tag, or the build may fail at the publishing step because a release could already exist for the configured current version number. Also note that all releases are created in Draft form and must be manually changed to Public before people can view them at https://github.com/AUGMXNT/perfi/releases

As of 2025-12-25, CI/release builds use `uv` for Python dependency management (`uv sync --frozen --all-groups` + `uv run pyinstaller ...`) and build the frontend with `npm ci` + `npx vite build` (not `npm run build`).
