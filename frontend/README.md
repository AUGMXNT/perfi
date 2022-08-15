# perfi Frontend

These are instructions to get the perfi Frontend dev server up and running and talking to a locally-running instance of the backend API server.

For more information, especially on how the perfi app is built, and how the frontend and backend interact, see `../README.md`


## Dependencies

1. Make sure you have `nodejs` and `npm` installed.
1. Run `npm install` to grab the js dependencies


## Running the dev server

1. First, create a `.env` file with the following contents:
    ```
    VITE_BACKEND_URL=http://localhost:8001
    ```
    **Important note:** The URL above should point to the location and port of where you have perfi's API server running. By default that will be `http://localhost:8001` but you may have changed it inside `../perfi/api.py` so check there if needed.

2. Next, run the perfi API server. From one directory up (above this README file), run `poetry run python perfi/api.py`.  Note the host/port that the API server is listening on and make sure it matches what you have in your `.env` from above.

3. Once the API server is running, start the frontend dev server with: `npm run dev`. This should start a local frontend dev server on `http://localhost:3000` and pop the window open in your default browser.

    **Important note:** If for some reason you are running your frontend dev server off a different host/port combination (other than `localhost:3000`), you will need to modify `../perfi/api.py` to add your frontend dev server host/port to the list of allowed origins for the API server's CORS Middleware config. Look for `CORSMiddleware` in `../perfi/api.py` to see where to add your frontend host/port config.

4. You should now be up and running with the browser frontend successfully talking to the python API server.
