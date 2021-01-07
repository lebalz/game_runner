# register task to startup python scripts or kill them as read only user...
inotifywait -m /app/running_games -e create -e moved_to |
    while read path action file; do
        echo "got new file: $action, $path, $file"
        if [[ $file == *.py ]]
        then
            # extract the stem of the file
            game=${file%%.*}
            # a file <game-name>.project contains the project folder
            project=$(cat "$path$game.project")
            # wait a little s.t. the page will be loaded before startup
            sleep 0.5
            # start the game as user game_runner in a new background task
            /bin/su -s /bin/bash -c "(cd /app/uploads/$project && /app/.heroku/python/bin/python3 $path$file &)" game_runner
        else
            if [[ $file == *.kill ]]
            then
                # extract the stem of the file
                game=${file%%.*}
                pid=$(cat "/home/game_runner/$file.pid")
                # get the parent process id
                ppid=$(ps -o ppid= -p $pid)
                # kill the shell first
                kill $ppid
                # ... and now the running python program
                kill $pid
                # clean up all touched files
                rm $path$game.project
                rm $path$game.py
                rm $path$game.kill
                rm /home/game_runner/$game.kill.pid
            fi
        fi
    done