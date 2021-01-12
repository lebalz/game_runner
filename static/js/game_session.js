/**
 * 
 * @param {MouseEvent} event 
 */
const on_game_start = (event, gameId) => {
    const current_id = localStorage.getItem('running_game_id')
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