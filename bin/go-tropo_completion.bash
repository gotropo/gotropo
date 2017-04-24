_go_tropo_completion() {
    COMPREPLY=( $( env COMP_WORDS="${COMP_WORDS[*]}" \
                   COMP_CWORD=$COMP_CWORD \
                   _GO_TROPO_COMPLETE=complete $1 ) )
    return 0
}

complete -F _go_tropo_completion -o default go-tropo;
