/**
 * 
 * @param {MouseEvent} event 
 */
const on_game_start = (event, gameId) => {
    current_id = localStorage.getItem('running_game_id');
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
        currentRating = localStorage.getItem(`rating-${gameId}`);
        if (currentRating === rating) {
            return
        }
        var xhttp = new XMLHttpRequest();
        xhttp.open("POST", "/game_vote", true);
        xhttp.setRequestHeader('Content-type', 'application/x-www-form-urlencoded');
        xhttp.onreadystatechange = function () {
            if (this.readyState == 4 && this.status == 200) {
                localStorage.setItem(`rating-${gameId}`, rating)
                location.reload();
            }
        }
        xhttp.send(`game_id=${gameId}&rating=${rating}`);
    }
    return;
}