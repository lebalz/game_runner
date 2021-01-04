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
                game=${file%%.*}
                pid=$(cat "/home/game_runner/$file.pid")
                ppid=$(ps -o ppid= -p $pid)
                kill $ppid
                kill $pid
                rm $path$game.project
                rm $path$game.py
                rm /home/game_runner/$game
            fi
        fi
    done