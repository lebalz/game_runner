/**
 * 
 * @param {MouseEvent} event 
 */
const on_game_start = (event, gameId) => {
    const current_id = localStorage.getItem('running_game_id')
    if (current_id) {
        var xhttp = new XMLHttpRequest();
        xhttp.open("POST", "/terminate_game", true);
        xhttp.setRequestHeader('Content-type', 'application/x-www-form-urlencoded');
        xhttp.send(`id=${gameId}`);
    }
    localStorage.setItem('running_game_id', current_id);
    return;
}