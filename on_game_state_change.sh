# register task to startup python scripts or kill them...
inotifywait -m /home/game_runner/.running_games -e create -e moved_to |
    while read path action file; do
        echo "got new file: $action, $path, $file"
        if [[ $file == *.py ]]
        then
            echo "run python file $file"
        else
            if [[ $file == *.kill ]]
            then
                echo "kill python file $file"
            fi
        fi
    done