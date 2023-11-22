# traceback-with variables: https://pypi.org/project/traceback-with-variables/
# Simplest usage in regular Python, for the whole program:
from traceback_with_variables import activate_by_import
import traceback_with_variables

import traceback
from typing import Any, Union

def filter_empty_in_dict_list_scalar(dict_list_scalar:Union[list, dict, Any]) -> Union[list, dict, Any]:
    """
    given a 'dict' or 'list' as input, removes all elements in these containers that are empty: scalars with None, strings that are '', lists and dicts that are empty.  Note that the filtering is in-place: modifies the passed list or dict

    Args:
        dict_list_scalar (Union[list, dict, Any]): see above
    """
    try:
        # depth first traveral
        if isinstance(dict_list_scalar, dict):
            keys_to_del:list = []
            for k in dict_list_scalar.keys():  
                filter_empty_in_dict_list_scalar(dict_list_scalar[k])
                
                # check if the 'key' is now None or empty.  If so, remove the 'key'
                if not dict_list_scalar[k]: 
                    # cannont do dict.pop(): RuntimeError: dictionary changed size during iteration
                    # dict_list_scalar.pop(k)
                    keys_to_del.append(k)
            
            # now delete the keys from the map
            for k in keys_to_del:
                dict_list_scalar.pop(k)
            
            return dict_list_scalar
        elif isinstance(dict_list_scalar, list):
            i = 0; length = len(dict_list_scalar)
            while i < length: 
                filter_empty_in_dict_list_scalar(dict_list_scalar[i])
            
                # check if element is now None (if scalar) or empty (if list or dict).  If so, remove the element from the list
                if not dict_list_scalar[i]:
                    dict_list_scalar.remove(dict_list_scalar[i])
                    i -= 1; length -= 1
                
                i += 1
            return dict_list_scalar
        else: # this must be a non container, like int, str, datatime.datetime
            return dict_list_scalar
    except Exception as e:
        # some excpetion, just log it..
        print(f"_filter_empty_in_dict_list_scalar(): Caught exception: {e}")
        traceback_with_variables.print_exc()
