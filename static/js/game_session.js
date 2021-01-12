/**
 * 
 * @param {MouseEvent} event 
 */
const on_game_start = (event, gameId) => {
    console.log('current game play id', current_id, 'new ID', gameId)
    if (current_id) {
        var xhttp = new XMLHttpRequest();
        xhttp.open("POST", "/terminate_game", true);
        xhttp.setRequestHeader('Content-type', 'application/x-www-form-urlencoded');
        xhttp.send(`id=${current_id}`);
    }
    localStorage.setItem('running_game_id', gameId);
    return;
}

const on_vote = (event, gameId, rating) => {
    if (gameId) {
        var xhttp = new XMLHttpRequest();
        xhttp.open("POST", "/game_vote", true);
        xhttp.setRequestHeader('Content-type', 'application/x-www-form-urlencoded');
        xhttp.onreadystatechange = function () {
            if (this.readyState == 4 && this.status == 200) {
                location.reload();
            }
        }
        xhttp.send(`game_id=${gameId}&rating=${rating}`);
    }
    return;
}