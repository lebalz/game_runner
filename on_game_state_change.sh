# register task to startup python scripts or kill them...
inotifywait -m /home/game_runner/.running_games -e create -e moved_to |
    while read path action file; do
        echo "got new file: $action, $path, $file"
        if [[ $file == *.py ]]
        then
            game=${file%%.*}
            project=$(cat "$path$game.project")
            /bin/su -s /bin/bash -c "(cd /app/uploads/$project && /app/.heroku/python/bin/python3 $path$file &)" game_runner
        else
            if [[ $file == *.kill ]]
            then
                echo "kill python file $file"
            fi
        fi
    done